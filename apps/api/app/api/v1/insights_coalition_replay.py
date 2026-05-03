"""Coalition replay endpoint — Tier 5 of the visibility roadmap.

`GET /insights/collaborations` — list past A2A coalition runs.
`GET /insights/collaborations/{blackboard_id}` — full timeline of
entries for replay (chronological, with author + role + content +
evidence pointers).

A2A coalitions persist their working memory in the `blackboards` +
`blackboard_entries` tables (PR shipped 2026-04-12). The live
CollaborationPanel renders an active session via Redis pub/sub;
this endpoint renders historical sessions from the persisted DB.

Curate-don't-dump (lineage from PR #256/#263/#265):
  - No tenant_id on response rows
  - Per-entry evidence is the raw JSON Authors stored — passed through
    so the replay UI can link to source artifacts. Capped at 50KB
    per row to bound payload size.
  - List endpoint paginated with cursor on (created_at DESC, id ASC).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.models.blackboard import Blackboard, BlackboardEntry
from app.models.user import User as UserModel

router = APIRouter()


_EVIDENCE_CAP_BYTES = 50_000


class CoalitionSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    chat_session_id: Optional[uuid.UUID]
    entry_count: int
    distinct_agents: int
    created_at: datetime
    updated_at: datetime


class CoalitionListResponse(BaseModel):
    rows: List[CoalitionSummary]
    next_cursor: Optional[str] = None
    has_more: bool = False


class ReplayEntry(BaseModel):
    id: uuid.UUID
    board_version: int
    entry_type: str
    content: str
    confidence: float
    author_agent_slug: str
    author_role: str
    status: str
    parent_entry_id: Optional[uuid.UUID]
    supersedes_entry_id: Optional[uuid.UUID]
    resolved_by_agent: Optional[str]
    resolution_reason: Optional[str]
    evidence: list  # passed through; capped at _EVIDENCE_CAP_BYTES per row
    created_at: datetime


class CoalitionReplayResponse(BaseModel):
    coalition: CoalitionSummary
    entries: List[ReplayEntry]


def _decode_cursor(cursor: Optional[str]):
    if not cursor:
        return None
    try:
        ts_str, id_str = cursor.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except (ValueError, AttributeError):
        return None


def _encode_cursor(ts: datetime, id_: uuid.UUID) -> str:
    return f"{ts.isoformat()}|{id_}"


def _summarize(bb, entry_count: int, distinct_agents: int) -> CoalitionSummary:
    return CoalitionSummary(
        id=bb.id,
        title=bb.title,
        status=bb.status,
        chat_session_id=bb.chat_session_id,
        entry_count=entry_count,
        distinct_agents=distinct_agents,
        created_at=bb.created_at,
        updated_at=bb.updated_at,
    )


@router.get("/collaborations", response_model=CoalitionListResponse)
def list_coalitions(
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = None,
):
    """List past coalition runs for this tenant, newest first."""
    from sqlalchemy import func

    tenant_id = current_user.tenant_id
    q = db.query(Blackboard).filter(Blackboard.tenant_id == tenant_id)

    decoded = _decode_cursor(cursor)
    if decoded:
        cur_ts, cur_id = decoded
        q = q.filter(
            (Blackboard.created_at < cur_ts)
            | ((Blackboard.created_at == cur_ts) & (Blackboard.id > cur_id))
        )

    q = q.order_by(Blackboard.created_at.desc(), Blackboard.id.asc())
    boards = q.limit(limit + 1).all()
    has_more = len(boards) > limit
    boards = boards[:limit]

    if not boards:
        return CoalitionListResponse(rows=[], has_more=False)

    # Bulk count entries + distinct agent slugs per board to avoid N+1.
    bids = [b.id for b in boards]
    agg_rows = (
        db.query(
            BlackboardEntry.blackboard_id,
            func.count(BlackboardEntry.id).label("entry_count"),
            func.count(func.distinct(BlackboardEntry.author_agent_slug)).label("distinct_agents"),
        )
        .filter(BlackboardEntry.blackboard_id.in_(bids))
        .group_by(BlackboardEntry.blackboard_id)
        .all()
    )
    agg = {row.blackboard_id: row for row in agg_rows}

    rows = []
    for bb in boards:
        a = agg.get(bb.id)
        rows.append(_summarize(
            bb,
            entry_count=int(a.entry_count) if a else 0,
            distinct_agents=int(a.distinct_agents) if a else 0,
        ))

    next_cursor = (
        _encode_cursor(boards[-1].created_at, boards[-1].id) if has_more else None
    )
    return CoalitionListResponse(rows=rows, next_cursor=next_cursor, has_more=has_more)


@router.get("/collaborations/{blackboard_id}", response_model=CoalitionReplayResponse)
def replay_coalition(
    blackboard_id: uuid.UUID,
    *,
    db: Session = Depends(deps.get_db),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Full chronological replay of a coalition run.

    Tenant-scoped — a tenant cannot read another tenant's blackboard
    even if they guess the UUID.
    """
    bb = (
        db.query(Blackboard)
        .filter(
            Blackboard.id == blackboard_id,
            Blackboard.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not bb:
        raise HTTPException(status_code=404, detail="Coalition not found.")

    raw_entries = (
        db.query(BlackboardEntry)
        .filter(BlackboardEntry.blackboard_id == bb.id)
        .order_by(BlackboardEntry.created_at.asc(), BlackboardEntry.id.asc())
        .all()
    )

    distinct_agents = {e.author_agent_slug for e in raw_entries}
    summary = _summarize(bb, len(raw_entries), len(distinct_agents))

    entries: List[ReplayEntry] = []
    for e in raw_entries:
        # Cap evidence payload size to keep the replay response bounded
        # for boards with very large evidence blobs.
        ev = e.evidence
        if isinstance(ev, list):
            import json
            try:
                serialized = json.dumps(ev)
            except (TypeError, ValueError):
                serialized = str(ev)
            if len(serialized) > _EVIDENCE_CAP_BYTES:
                ev = [{"_truncated": True, "_original_size_bytes": len(serialized)}]
        entries.append(ReplayEntry(
            id=e.id,
            board_version=e.board_version,
            entry_type=e.entry_type,
            content=e.content,
            confidence=float(e.confidence or 0.0),
            author_agent_slug=e.author_agent_slug,
            author_role=e.author_role,
            status=e.status,
            parent_entry_id=e.parent_entry_id,
            supersedes_entry_id=e.supersedes_entry_id,
            resolved_by_agent=e.resolved_by_agent,
            resolution_reason=e.resolution_reason,
            evidence=ev or [],
            created_at=e.created_at,
        ))

    return CoalitionReplayResponse(coalition=summary, entries=entries)
