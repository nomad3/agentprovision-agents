"""Append-only audit events for Luna desktop-control observations/actions."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class DesktopCommandEvent(Base):
    __tablename__ = "desktop_command_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    desktop_command_id = Column(
        UUID(as_uuid=True),
        ForeignKey("desktop_commands.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approval_id = Column(UUID(as_uuid=True), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    action = Column(String(64), nullable=False)
    capability = Column(String(64), nullable=False)
    outcome = Column(String(32), nullable=False)
    reason = Column(String(512), nullable=True)
    mode = Column(String(32), nullable=True)
    shell_id = Column(String(96), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("device_registry.id", ondelete="SET NULL"), nullable=True)
    event_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
