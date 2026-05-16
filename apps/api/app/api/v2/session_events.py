"""Alpha Control Plane v2 session-events API.

Two endpoints:

  GET /api/v2/sessions/{session_id}/events
      SSE stream of the channel-agnostic event envelope.

  GET /api/v2/sessions/{session_id}/events?since=<seq_no>&limit=<n>
      JSON replay of events since seq_no, paginated via next_cursor.
      Coalesces `cli_subprocess_stream` chunks into 5-second windows.

The two endpoints share the path; FastAPI dispatches based on whether
the request accepts text/event-stream or application/json.

Design: docs/plans/2026-05-15-alpha-control-plane-design.md §5, §5.4
Plan:   docs/plans/2026-05-15-alpha-control-plane-tier-0-1-plan.md §3
"""
from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-design §5.4
_REPLAY_WINDOW_HOURS = 24
_DEFAULT_REPLAY_LIMIT = 100
_MAX_REPLAY_LIMIT = 500
_SUBPROCESS_COALESCE_WINDOW_SECONDS = 5
_HEARTBEAT_INTERVAL_SECONDS = 15


def _ensure_session_visible(db: Session, session_id: _uuid.UUID, user: User) -> None:
    """Reject if the session doesn't exist or doesn't belong to the
    caller's tenant. Returns nothing on success; raises HTTPException
    on failure.
    """
    row = db.execute(
        text("SELECT tenant_id FROM chat_sessions WHERE id = :id"),
        {"id": session_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row[0] is None:
        # Legacy sessions without tenant_id — allow read for now; the
        # session_events rows themselves have NULL-UUID tenant_id and
        # carry no PII.
        return
    if str(row[0]) != str(user.tenant_id):
        raise HTTPException(status_code=404, detail="Session not found")


def _coalesce_subprocess_streams(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse consecutive `cli_subprocess_stream` events from the same
    platform within a 5-second window into a single synthetic event.

    Reduces replay response size for sessions with chatty subprocesses.
    Live SSE keeps original chunk granularity.
    """
    coalesced: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None
    pending_window_start: Optional[datetime] = None

    def _flush():
        nonlocal pending
        if pending is not None:
            coalesced.append(pending)
            pending = None

    for evt in events:
        if evt.get("type") != "cli_subprocess_stream":
            _flush()
            coalesced.append(evt)
            continue

        # parse ts → datetime
        ts_raw = evt.get("ts")
        try:
            ts = datetime.fromisoformat(ts_raw.rstrip("Z")) if ts_raw else datetime.utcnow()
        except Exception:
            ts = datetime.utcnow()

        platform = (evt.get("payload") or {}).get("platform")
        same_window = (
            pending is not None
            and (pending.get("payload") or {}).get("platform") == platform
            and pending_window_start is not None
            and (ts - pending_window_start).total_seconds()
                <= _SUBPROCESS_COALESCE_WINDOW_SECONDS
        )

        if same_window:
            # Merge chunk into pending event. Replace the chunks list
            # rather than mutating in place so the caller's input dicts
            # are never modified — keeps this helper a pure transformation.
            new_chunk = (evt.get("payload") or {}).get("chunk", "")
            chunks = list(pending["payload"].get("chunks", [])) + [new_chunk]
            pending["payload"]["chunks"] = chunks
            # Keep only last 3 chunks to bound the payload
            if len(chunks) > 3:
                pending["payload"]["chunks"] = chunks[-3:]
                pending["payload"]["chunks_truncated"] = True
            pending["payload"]["coalesced_count"] = (
                pending["payload"].get("coalesced_count", 1) + 1
            )
            pending["seq_no"] = evt["seq_no"]  # last seq_no in the window
        else:
            _flush()
            pending = {
                **evt,
                "payload": {
                    **(evt.get("payload") or {}),
                    "chunks": [(evt.get("payload") or {}).get("chunk", "")],
                    "coalesced_count": 1,
                },
            }
            pending_window_start = ts

    _flush()
    return coalesced


@router.get("/sessions/{session_id}/events")
def session_events(
    session_id: _uuid.UUID,
    request: Request,
    since: Optional[int] = Query(None, ge=0, description="Replay events with seq_no > this value"),
    limit: int = Query(_DEFAULT_REPLAY_LIMIT, ge=1, le=_MAX_REPLAY_LIMIT),
    user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Unified events endpoint.

    Behaviour depends on the Accept header:

    * `text/event-stream` (SSE): subscribe to live events on the
      `session:{id}:v2` Redis channel. Used by the cockpit/Tauri/CLI
      viewports.
    * any other Accept (or `application/json`): return a paginated
      replay of events since `seq_no`. Used by viewports on reconnect
      to catch up missed events.

    When called with `since=` AND SSE Accept, the SSE first replays
    any missed events as inline `data: {...}` frames (one per event),
    then continues with the live stream.
    """
    _ensure_session_visible(db, session_id, user)

    accept = (request.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return StreamingResponse(
            _sse_stream(session_id, db, since=since),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # JSON replay path
    if since is None:
        since = 0  # default: replay from session start

    # Check replay window cap (design §5.4)
    if since > 0:
        latest_seq = db.execute(
            text(
                "SELECT MAX(seq_no), MIN(created_at) "
                "FROM session_events WHERE session_id = :sid AND seq_no <= :since"
            ),
            {"sid": session_id, "since": since},
        ).first()
        # If the `since` row's created_at is older than the replay window cap,
        # tell the client to start fresh.
        if latest_seq and latest_seq[1] is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=_REPLAY_WINDOW_HOURS)
            # Make created_at tz-aware if naive
            anchor = latest_seq[1]
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            if anchor < cutoff:
                latest_overall = db.execute(
                    text("SELECT COALESCE(MAX(seq_no), 0) FROM session_events WHERE session_id = :sid"),
                    {"sid": session_id},
                ).scalar()
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "replay_window_expired",
                        "latest_seq_no": int(latest_overall),
                        "replay_window_hours": _REPLAY_WINDOW_HOURS,
                    },
                )

    rows = db.execute(
        text(
            "SELECT id, session_id, tenant_id, seq_no, event_type, payload, created_at "
            "FROM session_events "
            "WHERE session_id = :sid AND seq_no > :since "
            "ORDER BY seq_no ASC "
            "LIMIT :limit"
        ),
        {"sid": session_id, "since": since, "limit": limit},
    ).all()

    events: List[Dict[str, Any]] = [
        {
            "event_id": str(r[0]),
            "session_id": str(r[1]),
            "tenant_id": str(r[2]) if r[2] else None,
            "seq_no": int(r[3]),
            "type": r[4],
            "payload": r[5] if isinstance(r[5], dict) else json.loads(r[5]),
            "ts": (r[6].isoformat() if r[6] else None),
        }
        for r in rows
    ]

    # Compaction on replay (design §5)
    events = _coalesce_subprocess_streams(events)

    # next_cursor = highest seq_no returned if we hit the limit, else null
    next_cursor: Optional[int] = None
    if rows and len(rows) == limit:
        next_cursor = int(rows[-1][3])

    latest_seq = db.execute(
        text("SELECT COALESCE(MAX(seq_no), 0) FROM session_events WHERE session_id = :sid"),
        {"sid": session_id},
    ).scalar()

    return {
        "events": events,
        "next_cursor": next_cursor,
        "latest_seq_no": int(latest_seq),
    }


def _sse_stream(
    session_id: _uuid.UUID,
    db: Session,
    since: Optional[int] = None,
) -> Generator[str, None, None]:
    """SSE generator: replay (if `since` provided) then live tail.

    Subscribes to the new v2 Redis channel `session:{id}:v2` which
    carries the full envelope (`event_id`, `seq_no`, etc.). The legacy
    `session:{id}` channel keeps serving v1 consumers untouched.
    """
    # Emit an initial heartbeat-comment immediately so Cloudflare /
    # any intermediate proxy flushes the 200 response headers to the
    # client. Without this, fetch() in the browser hangs at
    # "connecting" forever when the session has no events to replay
    # and no live events arrive — the body stays empty and the
    # response headers never make it through. SSE comments (starting
    # with ":") are ignored by EventSource consumers but force a
    # flush, which is exactly what we want here.
    yield ": connected\n\n"

    # Optional replay: emit any missed events first
    if since is not None and since >= 0:
        rows = db.execute(
            text(
                "SELECT id, session_id, tenant_id, seq_no, event_type, payload, created_at "
                "FROM session_events "
                "WHERE session_id = :sid AND seq_no > :since "
                "ORDER BY seq_no ASC LIMIT :limit"
            ),
            {"sid": session_id, "since": since, "limit": _MAX_REPLAY_LIMIT},
        ).all()
        for r in rows:
            envelope = {
                "event_id": str(r[0]),
                "session_id": str(r[1]),
                "tenant_id": str(r[2]) if r[2] else None,
                "seq_no": int(r[3]),
                "type": r[4],
                "payload": r[5] if isinstance(r[5], dict) else json.loads(r[5]),
                "ts": (r[6].isoformat() if r[6] else None),
            }
            yield f"data: {json.dumps(envelope)}\n\n"

    # Live tail via Redis pub/sub. Use get_message(timeout=) instead of
    # listen() so we wake up regularly to emit heartbeats and keep the
    # tunnel from idle-timing out — pubsub.listen() blocks indefinitely
    # if no message arrives, which silenced the keepalive and gave
    # Cloudflare a 100s read-idle window to drop the response.
    channel = f"session:{session_id}:v2"
    last_heartbeat = time.time()
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        pubsub.subscribe(channel)
        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message and message.get("type") == "message":
                yield f"data: {message['data']}\n\n"
            now = time.time()
            if now - last_heartbeat > _HEARTBEAT_INTERVAL_SECONDS:
                yield ": heartbeat\n\n"
                last_heartbeat = now
    except Exception as e:
        logger.warning("v2 SSE error on session %s: %s", session_id, e)
        yield (
            "data: " + json.dumps({
                "type": "stream_error",
                "payload": {"detail": "Stream connection lost; reconnect with since=<last_seq_no>"},
            }) + "\n\n"
        )
