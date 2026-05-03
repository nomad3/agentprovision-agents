"""User Preference — learned or explicit communication preferences."""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    preference_type = Column(String(50), nullable=False)
    # As of migration 114 `value` is nullable; rich payloads use value_json instead.
    value = Column(String(200), nullable=True)
    value_json = Column(JSONB, nullable=True)
    confidence = Column(Float, default=0.5)
    evidence_count = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
