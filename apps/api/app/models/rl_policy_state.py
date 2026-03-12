import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base


class RLPolicyState(Base):
    __tablename__ = "rl_policy_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    decision_point = Column(String(50), nullable=False)
    weights = Column(JSONB, nullable=False, default=dict)
    version = Column(String(50), nullable=False, default="v1")
    experience_count = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    exploration_rate = Column(Float, nullable=False, default=0.1)
