"""Luna Phase 5.2/5.3 — governed perception quarantine artifact registry.

One row per governed screenshot ("observation") the Luna client captures. The
PNG bytes live on an API-only quarantine volume (``OBSERVATION_QUARANTINE_ROOT``),
never the agent-shared workspaces volume; this row is the metadata + the cleanup
handle.

P5.2 is transport-only: artifacts land ``not_planner_safe`` with no byte-retrieval
path. P5.3 adds the redactor (the first controlled reader): it claims a row
(``redacting``), writes a redacted copy to ``redacted_storage_path``, HARD-DELETES
the raw bytes (``raw_deleted_at`` — a prerequisite, so raw + redacted never
coexist), and only then flips ``redaction_status`` to ``planner_safe``. Fail-closed:
any error leaves the artifact ``not_planner_safe`` with no redacted output.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

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
    # not_planner_safe (P5.2 default) -> redacting (claimed) -> planner_safe (P5.3).
    # Plain String, no enum/check — the new values need no DDL (migration 171).
    redaction_status = Column(String(32), nullable=False, default="not_planner_safe")
    source_window_bundle_id = Column(String(255), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # ── P5.3 redactor (migration 171) ────────────────────────────────────────
    # The redacted (planner-safe) copy under the same API-only quarantine root.
    redacted_storage_path = Column(Text, nullable=True)
    redacted_at = Column(DateTime(timezone=True), nullable=True)
    # raw_deleted_at is a PREREQUISITE of planner_safe — set only after the raw
    # bytes are hard-deleted, so raw + redacted never coexist. Retrieval (P5.3b)
    # requires it non-null.
    raw_deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Byte-free redaction audit: region COUNT + coarse category + model/redactor
    # version + verdict + failure-reason-code. Never snippets/offsets/box sizes.
    redaction_meta = Column(JSONB, nullable=True)
    # Worker lease (claim) fields — SELECT … FOR UPDATE SKIP LOCKED + timeout
    # recovery so a crashed worker's 'redacting' row is reclaimed, not stuck.
    redact_claimed_at = Column(DateTime(timezone=True), nullable=True)
    redact_claimed_by = Column(Text, nullable=True)
    redact_attempts = Column(Integer, nullable=False, default=0, server_default="0")
