"""Internal-key write endpoint for streaming CLI subprocess output back
into the v2 session-events log.

Background
----------
The code-worker runs the actual CLI subprocesses (Claude Code, Codex,
Gemini, Copilot, OpenCode) inside its container and historically has
*no* path to publish ``cli_subprocess_stream`` events on its own — it
has no Redis credentials and no Postgres credentials. Previous worker
→ API fan-out (heartbeat-missed, MCP) used HTTPS with the shared
``X-Internal-Key``; this endpoint follows that same pattern for the
streaming-output path.

Design
------
- POST ``/api/v2/internal/sessions/{session_id}/events``
- ``X-Internal-Key`` auth (mirrors ``internal_session_events.py``)
- Body: ``{tenant_id, type, payload}``
- ``type`` is whitelisted to ``{"cli_subprocess_stream"}`` as
  defense-in-depth — even with a leaked key the worker can NEVER
  publish ``chat_message`` or other privileged event types here.
- ``session_id`` must belong to ``tenant_id`` (cross-tenant 404).
- On ``payload.batch`` (list of chunk dicts), the endpoint splits the
  batch and calls ``publish_session_event`` once per chunk so each
  chunk gets its own deterministic ``seq_no`` — replay reconstructs
  the original ordering even if the worker re-batched across HTTP
  retries.
- On a single non-batched payload, one publish_session_event call.

Plan: docs/plans/2026-05-16-terminal-full-cli-output.md §4.2
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.services.collaboration_events import publish_session_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Defense in depth: even with a valid internal key, the worker can ONLY
# publish stream-type events through this endpoint. Other event types
# (chat_message, auto_quality_score, cli_subprocess_started/complete)
# stay owned by the API itself — leaking the key never gives a peer
# the ability to spoof those.
_ALLOWED_TYPES = frozenset({"cli_subprocess_stream"})


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    # Mirrors internal_session_events.py:36-46 — never trust an empty
    # header just because the configured secret happens to be empty.
    if not x_internal_key or x_internal_key not in (
        settings.API_INTERNAL_KEY,
        settings.MCP_API_KEY,
    ):
        raise HTTPException(status_code=401, detail="Invalid internal key")


@router.post("/internal/sessions/{session_id}/events")
def write_internal_session_event(
    session_id: _uuid.UUID,
    body: Dict[str, Any] = Body(...),
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
):
    """Persist + fan out a stream event coming from the code-worker.

    Body shape:
        {
          "tenant_id": "<uuid>",
          "type":      "cli_subprocess_stream",
          "payload":   { ... }      # may contain a `batch: [...]` list
        }

    Returns a list of envelopes for each emitted event (one per chunk
    if batched, otherwise a single-item list).
    """
    tenant_raw = body.get("tenant_id")
    event_type = body.get("type") or ""
    payload = body.get("payload") or {}

    if not tenant_raw:
        raise HTTPException(status_code=400, detail="tenant_id required")
    try:
        tenant_id = _uuid.UUID(str(tenant_raw))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="tenant_id must be a UUID")

    if event_type not in _ALLOWED_TYPES:
        # 400, not 401 — the auth succeeded but the payload type is not
        # writable through this internal endpoint. We never want a worker
        # to publish chat_message etc. with the internal key.
        raise HTTPException(
            status_code=400,
            detail=f"event type '{event_type}' not allowed via internal stream endpoint",
        )

    # Cross-tenant visibility check — same 404 shape as the read endpoint
    # so we don't leak that a session exists in another tenant.
    row = db.execute(
        text("SELECT tenant_id FROM chat_sessions WHERE id = :id"),
        {"id": session_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row[0] is not None and str(row[0]) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Batch fan-out — one publish per chunk so each gets its own seq_no
    # (deterministic replay even if the worker re-batched on retry).
    envelopes: List[Dict[str, Any]] = []
    batch = payload.get("batch")
    if isinstance(batch, list) and batch:
        platform = payload.get("platform")
        for chunk in batch:
            if not isinstance(chunk, dict):
                continue
            sub_payload = {
                "platform": platform,
                **{k: v for k, v in chunk.items() if k != "platform"},
            }
            try:
                env = publish_session_event(
                    str(session_id),
                    event_type,
                    sub_payload,
                    tenant_id=str(tenant_id),
                )
                envelopes.append({"seq_no": env.get("seq_no"), "event_id": env.get("event_id")})
            except Exception:
                logger.warning(
                    "internal stream publish failed (sid=%s, chunk drop)",
                    session_id, exc_info=True,
                )
        return {"events": envelopes}

    # Single-chunk path
    try:
        env = publish_session_event(
            str(session_id),
            event_type,
            payload,
            tenant_id=str(tenant_id),
        )
    except Exception:
        logger.warning(
            "internal stream publish failed (sid=%s)", session_id, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="publish failed")
    return {"events": [{"seq_no": env.get("seq_no"), "event_id": env.get("event_id")}]}
