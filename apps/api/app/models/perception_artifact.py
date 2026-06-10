"""Luna Phase 5.2 — governed perception quarantine artifact registry.

One row per governed screenshot ("observation") the Luna client captures. The
PNG bytes live on an API-only quarantine volume (``OBSERVATION_QUARANTINE_ROOT``),
never the agent-shared workspaces volume; this row is the metadata + the cleanup
handle. P5.2 is transport-only: there is no byte-retrieval path until P5.3 adds a
validator + redactor, so ``redaction_status`` is always ``not_planner_safe`` here.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class PerceptionArtifact(Base):
    __tablename__ = "perception_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shell_id = Column(String(96), nullable=False)
    device_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_registry.id", ondelete="SET NULL"),
        nullable=True,
    )
    artifact_type = Column(String(32), nullable=False, default="screenshot")
    # Path under OBSERVATION_QUARANTINE_ROOT (API-only volume). Bytes never leave it.
    storage_path = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    # P5.2 always 'not_planner_safe'; P5.3 will set 'redacted' before any consumer.
    redaction_status = Column(String(32), nullable=False, default="not_planner_safe")
    source_window_bundle_id = Column(String(255), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
