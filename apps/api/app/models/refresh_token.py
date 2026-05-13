"""ORM mirror of the `refresh_tokens` table (migration 130).

The server-side companion to the long-lived CLI session pattern. Code that
needs to mint, rotate, list, or revoke refresh tokens lives in
`app/services/refresh_tokens.py`; this module is intentionally just the
schema mapping plus a couple of helpers (`is_active`).
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # sha256(secret) — the raw secret only flows once, at issue time.
    token_hash = Column(String(64), nullable=False, unique=True)
    # Self-reference for rotation chains; null on the first link.
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id"),
        nullable=True,
    )
    device_label = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    ip_inet = Column(INET, nullable=True)
    expires_at = Column(DateTime(), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime(), nullable=True)
    revoked_at = Column(DateTime(), nullable=True)
    revoked_reason = Column(Text, nullable=True)

    user = relationship("User")
    # Cycle-safe child relationship — used by reuse-detection to walk
    # forward in the chain when revoking on a replay attempt.
    parent = relationship("RefreshToken", remote_side=[id], backref="children")

    def is_active(self, now: datetime | None = None) -> bool:
        """Live = not revoked and not past expiry. Mirrors the WHERE
        clause in the listing endpoint so callers don't reimplement it."""
        now = now or datetime.utcnow()
        if self.revoked_at is not None:
            return False
        return self.expires_at > now

    def time_remaining(self, now: datetime | None = None) -> timedelta:
        """Best-effort TTL surfaced in `alpha sessions list`."""
        now = now or datetime.utcnow()
        delta = self.expires_at - now
        return delta if delta.total_seconds() > 0 else timedelta(0)
