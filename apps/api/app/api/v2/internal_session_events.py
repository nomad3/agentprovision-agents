"""Internal-key read endpoint for session_events — feeds the MCP tool
`read_session_events`.

The public /api/v2/sessions/{id}/events endpoint requires a user JWT;
the MCP server doesn't have one when an agent calls back from a worker
context. This endpoint mirrors the JSON replay path of the public
endpoint but authenticates via X-Internal-Key and scopes by an
explicit tenant_id query param.

Read-only. No SSE here — agents poll.

Design: docs/plans/2026-05-15-alpha-control-center-phase-2-design.md
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    # Guard against the "empty header matches an unset/empty setting"
    # case — if API_INTERNAL_KEY or MCP_API_KEY is "" or None, the
    # `in` tuple would accept a missing header.
    if not x_internal_key or x_internal_key not in (
        settings.API_INTERNAL_KEY,
        settings.MCP_API_KEY,
    ):
        raise HTTPException(status_code=401, detail="Invalid internal key")


@router.get("/internal/session-events/{session_id}")
def read_session_events(
    session_id: _uuid.UUID,
    tenant_id: _uuid.UUID = Query(..., description="Tenant scoping; must match the session's tenant"),
    since: int = Query(0, ge=0, description="Return events with seq_no > since"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    _auth: None = Depends(_verify_internal_key),
    db: Session = Depends(deps.get_db),
):
    """Return paginated session events for a session.

    Mirrors the public v2 JSON replay envelope so MCP-tool callers and
    SPA callers see the same shape. Tenant mismatch returns 404 to avoid
    leaking that a session exists in another tenant.
    """
    # Verify the session belongs to this tenant.
    row = db.execute(
        text("SELECT tenant_id FROM chat_sessions WHERE id = :id"),
        {"id": session_id},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row[0] is not None and str(row[0]) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Session not found")

    rows = db.execute(
        text(
            "SELECT id, session_id, tenant_id, seq_no, event_type, payload, created_at "
            "FROM session_events "
            "WHERE session_id = :sid AND seq_no > :since "
            "ORDER BY seq_no ASC LIMIT :limit"
        ),
        {"sid": session_id, "since": since, "limit": limit},
    ).all()

    events = [
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
        "latest_seq_no": int(latest_seq or 0),
    }
