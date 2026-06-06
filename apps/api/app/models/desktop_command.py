"""Desktop command queue row for governed Luna computer-use actions."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class DesktopCommand(Base):
    __tablename__ = "desktop_commands"
    __table_args__ = (
        Index(
            "idx_desktop_commands_tenant_nonce",
            "tenant_id",
            "nonce",
            unique=True,
            postgresql_where=text("nonce IS NOT NULL"),
            sqlite_where=text("nonce IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shell_id = Column(String(96), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("device_registry.id", ondelete="SET NULL"), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4, index=True)
    capability = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    source = Column(String(32), nullable=False, default="api")
    nonce = Column(String(96), nullable=True)
    payload = Column(JSONB, nullable=False, default=dict)
    lease_owner_shell_id = Column(String(96), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
