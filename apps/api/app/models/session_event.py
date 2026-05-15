"""SessionEvent — persisted log of the channel-agnostic Alpha Control Plane
event stream.

Every event published via `publish_session_event` in
`apps.api.app.services.collaboration_events` writes a row here under a
per-session advisory lock, then fans out via Redis. Disconnected
viewports (web cockpit, Tauri, alpha CLI) catch up by reading rows
since their last-seen `seq_no` via `GET /api/v2/sessions/{id}/events`.

See:
* docs/plans/2026-05-15-alpha-control-plane-design.md §5.1
* docs/plans/2026-05-15-alpha-control-plane-tier-0-1-plan.md §1
* apps/api/migrations/133_session_events.sql
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "seq_no", name="session_events_session_seq_unique"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # documentation; the UNIQUE constraint already covers it
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    # BIGINT in the migration; SQLAlchemy maps via Integer (PG infers BIGINT
    # from BIGINT column type at the DB level — model uses Integer for
    # simpler typing on the Python side).
    seq_no = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
