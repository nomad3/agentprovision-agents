import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class WhatsappSessionBackup(Base):
    """Rolling known-good snapshots of a WhatsApp (neonize) device session.

    The "current" session lives in ``channel_accounts.session_blob``; this
    table is the recovery tier. Only blobs that passed validation
    (``PRAGMA integrity_check`` + the device-key assertion) are written
    here with ``validation_status='ok'`` — see
    ``docs/plans/2026-06-02-whatsapp-session-durability-design.md`` §3.

    Restore order is current → newest ``ok`` backup → next → …, so a
    corrupt or mid-write current blob never forces a QR re-pair.
    """

    __tablename__ = "whatsapp_session_backups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    account_id = Column(String(64), nullable=False, server_default="default")
    # timezone-aware + NOT NULL to match migration 157's TIMESTAMPTZ NOT NULL
    # column and the session_event.py precedent (review F1).
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    # gzip-compressed neonize SQLite snapshot (validated before insert).
    blob = Column(LargeBinary, nullable=False)
    # sha256 of the raw (decompressed) SQLite bytes — dedupes unchanged saves.
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    # Only 'ok' rows are restore candidates; writer only ever inserts 'ok'.
    validation_status = Column(String(16), nullable=False, server_default="ok")
    # 'shutdown' / 'connected' / 'disconnected' / 'pair' / 'heartbeat' / 'runtime'
    source_event = Column(String(32), nullable=True)

    # Keep the model-built (create_all) schema byte-compatible with migration
    # 157 — the CHECK constraint and the composite newest-first index (review F2).
    __table_args__ = (
        CheckConstraint(
            "validation_status IN ('ok', 'pending', 'corrupt')",
            name="whatsapp_session_backups_validation_check",
        ),
        Index(
            "idx_wa_session_backups_acct_created",
            "tenant_id",
            "account_id",
            created_at.desc(),
        ),
    )

    tenant = relationship("Tenant")
