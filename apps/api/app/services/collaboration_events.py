"""Redis pub/sub publisher for collaboration events.

Two channel types:
  session:{chat_session_id}      — session-level events (collaboration_started)
  collaboration:{collab_id}      — per-collaboration events (phase_started, blackboard_entry, ...)

Alpha Control Plane (PR-2): `publish_session_event` now also persists
every event in the `session_events` Postgres table BEFORE Redis fan-out,
so disconnected viewports can replay since their last-seen `seq_no`.

Failure ordering:
  * Postgres INSERT fails → exception bubbles to caller, Redis publish
    is skipped. The caller decides whether to retry.
  * Postgres commits + Redis publish fails → log warning, return the
    persisted envelope. Live SSE listeners miss it but the next
    reconnect-with-since=seq_no replay recovers it (see design §5.4).

`publish_event` (collaboration-scoped) keeps the legacy ephemeral
behaviour — those events are coalition lifecycle signals that don't
need replay. We may persist them later if needed.

Design: docs/plans/2026-05-15-alpha-control-plane-design.md §5.1
"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Generator, Optional

import redis
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[redis.ConnectionPool] = None


def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


def _get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())


def publish_event(collaboration_id: str, event_type: str, payload: dict) -> None:
    """Publish a per-collaboration event to Redis pub/sub."""
    channel = f"collaboration:{collaboration_id}"
    data = {
        "event_type": event_type,
        "payload": payload,
        "timestamp": time.time(),
    }
    message = json.dumps(data)
    try:
        r = _get_redis()
        r.publish(channel, message)
    except Exception as e:
        logger.warning("Redis publish failed (collaboration %s): %s", collaboration_id, e)


def publish_session_event(
    chat_session_id: str,
    event_type: str,
    payload: dict,
    *,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist + fan out a session-level event.

    Writes a row to `session_events` under a per-session advisory lock
    (allocating the next `seq_no` for this session), then publishes the
    full envelope to Redis. Returns the envelope so callers can ack the
    `event_id` / `seq_no` to clients.

    Backward-compat: existing callers pass only the three positional
    args; `tenant_id` is optional. If omitted, the row is still
    persisted with `tenant_id` resolved from the session row (best-
    effort; if unresolvable we fall back to the all-zeros UUID and
    log a warning — retention sweep still works by created_at).

    Failure ordering (see module docstring + design §5.1):
      * Postgres INSERT fails → exception raised; Redis publish skipped.
      * Postgres commits, Redis publish fails → log warning, return
        envelope so the caller's HTTP response still has the seq_no.

    Legacy v1 wire format (sent on the same Redis channel for current
    consumers like ChatPage.js):
        {"event_type": ..., "payload": ..., "timestamp": ...}
    is preserved alongside the new envelope so the v1 SSE endpoint can
    continue to deliver it without translation.
    """
    # Lazy-import to avoid a circular dep with app.db.session
    from app.db.session import SessionLocal

    envelope: Dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "session_id": str(chat_session_id),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "ts": datetime.utcnow().isoformat(),
        "type": event_type,
        "seq_no": None,  # filled in after INSERT
        "payload": payload,
    }

    db = SessionLocal()
    try:
        # Per-session advisory lock; auto-releases at COMMIT/ROLLBACK.
        # hashtext returns int4 — fine for advisory_xact_lock(bigint).
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:sid))"),
            {"sid": str(chat_session_id)},
        )
        # Allocate seq_no = MAX(seq_no) + 1 for this session.
        next_seq = db.execute(
            text(
                "SELECT COALESCE(MAX(seq_no), 0) + 1 "
                "FROM session_events WHERE session_id = :sid"
            ),
            {"sid": chat_session_id},
        ).scalar()
        envelope["seq_no"] = int(next_seq)

        # Resolve tenant_id from chat_sessions if caller didn't supply one.
        if envelope["tenant_id"] is None:
            resolved = db.execute(
                text("SELECT tenant_id FROM chat_sessions WHERE id = :sid"),
                {"sid": chat_session_id},
            ).scalar()
            if resolved:
                envelope["tenant_id"] = str(resolved)
            else:
                logger.warning(
                    "publish_session_event: could not resolve tenant_id for "
                    "session=%s; persisting with NULL UUID",
                    chat_session_id,
                )
                envelope["tenant_id"] = str(uuid.UUID(int=0))

        db.execute(
            text(
                "INSERT INTO session_events "
                "(id, session_id, tenant_id, seq_no, event_type, payload) "
                "VALUES (:id, :sid, :tid, :seq, :type, CAST(:payload AS jsonb))"
            ),
            {
                "id": envelope["event_id"],
                "sid": chat_session_id,
                "tid": envelope["tenant_id"],
                "seq": envelope["seq_no"],
                "type": event_type,
                "payload": json.dumps(payload),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Best-effort live fan-out. Failure does NOT raise — replay will
    # recover (design §5.4).
    channel = f"session:{chat_session_id}"
    # Legacy v1 envelope (current consumers expect this exact shape).
    legacy_data = {
        "event_type": event_type,
        "payload": payload,
        "timestamp": time.time(),
    }
    try:
        r = _get_redis()
        # Publish BOTH wire formats so the existing /api/v1 SSE endpoint
        # and the new /api/v2 SSE endpoint can each render their
        # subscribers correctly. The v2 envelope rides under a distinct
        # JSON shape with `event_id`/`seq_no`; the v1 consumer treats
        # unknown keys as no-ops.
        r.publish(channel, json.dumps(legacy_data))
        r.publish(channel + ":v2", json.dumps(envelope))
    except Exception as exc:
        logger.warning(
            "Redis publish failed (session %s, event_id %s): %s — "
            "replay will recover via /api/v2/sessions/{id}/events?since=seq_no",
            chat_session_id,
            envelope["event_id"],
            exc,
        )

    return envelope


def subscribe_collaboration(collaboration_id: str) -> Generator[str, None, None]:
    """SSE generator for collaboration events via Redis pub/sub.

    Yields Server-Sent Events strings. Reconnects on failure (up to 3 attempts).
    Closes when collaboration_completed event received.
    """
    channel = f"collaboration:{collaboration_id}"
    attempts = 0
    max_attempts = 3
    heartbeat_interval = 15  # seconds

    while attempts < max_attempts:
        try:
            r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe(channel)
            last_heartbeat = time.time()

            for message in pubsub.listen():
                if message["type"] == "message":
                    attempts = 0  # reset on successful message
                    yield f"data: {message['data']}\n\n"

                    # Check if collaboration is done — close stream
                    try:
                        data = json.loads(message["data"])
                        if data.get("event_type") == "collaboration_completed":
                            pubsub.unsubscribe(channel)
                            return
                    except Exception:
                        pass

                # Heartbeat to keep connection alive through proxies
                if time.time() - last_heartbeat > heartbeat_interval:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()

        except Exception as e:
            attempts += 1
            logger.warning("Redis subscription error (attempt %d/%d): %s", attempts, max_attempts, e)
            if attempts < max_attempts:
                time.sleep(1)
            else:
                yield f"data: {json.dumps({'event_type': 'error', 'payload': {'detail': 'Stream connection lost'}})}\n\n"


def subscribe_session(chat_session_id: str) -> Generator[str, None, None]:
    """SSE generator for session-level events (collaboration_started, etc.)."""
    channel = f"session:{chat_session_id}"
    attempts = 0
    max_attempts = 3
    heartbeat_interval = 15

    while attempts < max_attempts:
        try:
            r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe(channel)
            last_heartbeat = time.time()

            for message in pubsub.listen():
                if message["type"] == "message":
                    attempts = 0
                    yield f"data: {message['data']}\n\n"

                if time.time() - last_heartbeat > heartbeat_interval:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.time()

        except Exception as e:
            attempts += 1
            logger.warning("Redis session subscription error (attempt %d/%d): %s", attempts, max_attempts, e)
            if attempts < max_attempts:
                time.sleep(1)
            else:
                yield f"data: {json.dumps({'event_type': 'error', 'payload': {'detail': 'Stream connection lost'}})}\n\n"
