"""SkillRegistry model — DB metadata index for file-based skills."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class SkillRegistry(Base):
    __tablename__ = "skill_registry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    slug = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    tier = Column(String(20), nullable=False, default="native")
    category = Column(String(50), nullable=False, default="general")
    tags = Column(JSONB, default=[])
    auto_trigger_description = Column(Text, nullable=True)
    chain_to = Column(JSONB, default=[])
    engine = Column(String(20), nullable=False, default="python")
    is_published = Column(Boolean, default=False)
    source_repo = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
