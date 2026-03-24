"""Agent identity profiles for self-model persistence."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentIdentityProfile(Base):
    """Auditable operating profile for an agent within a tenant."""

    __tablename__ = "agent_identity_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_slug", name="uq_agent_identity_profile"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    agent_slug = Column(String(100), nullable=False)

    # Core identity
    role = Column(String(200), nullable=False, default="general assistant")
    mandate = Column(Text)
    domain_boundaries = Column(JSONB, nullable=False, default=list)

    # Tool access
    allowed_tool_classes = Column(JSONB, nullable=False, default=list)
    denied_tool_classes = Column(JSONB, nullable=False, default=list)

    # Behavioral parameters
    escalation_threshold = Column(String(30), nullable=False, default="medium")
    planning_style = Column(String(50), nullable=False, default="step_by_step")
    communication_style = Column(String(50), nullable=False, default="professional")
    risk_posture = Column(String(30), nullable=False, default="moderate")

    # Learned traits
    strengths = Column(JSONB, nullable=False, default=list)
    weaknesses = Column(JSONB, nullable=False, default=list)
    preferred_strategies = Column(JSONB, nullable=False, default=list)
    avoided_strategies = Column(JSONB, nullable=False, default=list)

    # Operating principles
    operating_principles = Column(JSONB, nullable=False, default=list)
    success_criteria = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
