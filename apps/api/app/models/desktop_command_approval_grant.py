"""Approval grants consumed by Luna desktop command claims."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class DesktopCommandApprovalGrant(Base):
    __tablename__ = "desktop_command_approval_grants"
    __table_args__ = (
        Index(
            "idx_desktop_command_approval_grants_tenant_status",
            "tenant_id",
            "status",
            "expires_at",
        ),
        Index(
            "idx_desktop_command_approval_grants_session_shell",
            "session_id",
            "shell_id",
            "created_at",
        ),
        Index(
            "idx_desktop_command_approval_grants_command",
            "desktop_command_id",
        ),
        Index(
            "idx_desktop_command_approval_grants_active_command",
            "tenant_id",
            "desktop_command_id",
            unique=True,
            postgresql_where=text("desktop_command_id IS NOT NULL AND status = 'active'"),
            sqlite_where=text("desktop_command_id IS NOT NULL AND status = 'active'"),
        ),
    )

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
    shell_id = Column(String(96), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("device_registry.id", ondelete="SET NULL"), nullable=True)
    desktop_command_id = Column(
        UUID(as_uuid=True),
        ForeignKey("desktop_commands.id", ondelete="CASCADE"),
        nullable=True,
    )
    risk_tier = Column(String(32), nullable=False)
    capability = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="active", index=True)
    target_binding = Column(JSONB, nullable=False, default=dict)
    max_actions = Column(Integer, nullable=False, default=1)
    remaining_actions = Column(Integer, nullable=False, default=1)
    approved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
