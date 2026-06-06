"""Single-use signed-envelope nonces for Luna desktop commands."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class DesktopCommandEnvelopeNonce(Base):
    __tablename__ = "desktop_command_envelope_nonces"
    __table_args__ = (
        Index(
            "idx_desktop_command_envelope_nonces_tenant_nonce",
            "tenant_id",
            "nonce",
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    desktop_command_id = Column(
        UUID(as_uuid=True),
        ForeignKey("desktop_commands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shell_id = Column(String(96), nullable=False, index=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("device_registry.id", ondelete="SET NULL"), nullable=True)
    nonce = Column(String(96), nullable=False)
    envelope_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="issued", index=True)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
