"""Tenant-scoped safety policy overrides, trust profiles, and evidence packs."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class TenantActionPolicy(Base):
    """Tenant override for a governed action on a specific channel."""

    __tablename__ = "tenant_action_policies"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "action_type",
            "action_name",
            "channel",
            name="uq_tenant_action_policy",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    action_name = Column(String(150), nullable=False)
    channel = Column(String(50), nullable=False, default="*")
    decision = Column(String(30), nullable=False)
    rationale = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    creator = relationship("User")


class SafetyEvidencePack(Base):
    """Persisted evidence snapshot attached to a sensitive governed action."""

    __tablename__ = "safety_evidence_packs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    action_type = Column(String(50), nullable=False)
    action_name = Column(String(150), nullable=False)
    channel = Column(String(50), nullable=False)
    decision = Column(String(30), nullable=False)
    decision_source = Column(String(50), nullable=False)
    risk_class = Column(String(50), nullable=False)
    risk_level = Column(String(20), nullable=False)
    evidence_required = Column(Boolean, nullable=False, default=False)
    evidence_sufficient = Column(Boolean, nullable=False, default=False)
    world_state_facts = Column(JSONB, nullable=False, default=list)
    recent_observations = Column(JSONB, nullable=False, default=list)
    assumptions = Column(JSONB, nullable=False, default=list)
    uncertainty_notes = Column(JSONB, nullable=False, default=list)
    proposed_action = Column(JSONB, nullable=False, default=dict)
    expected_downside = Column(Text)
    context_summary = Column(Text)
    context_ref = Column(JSONB, nullable=False, default=dict)
    agent_slug = Column(String(100))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    tenant = relationship("Tenant")
    creator = relationship("User")


class AgentTrustProfile(Base):
    """Tenant-scoped trust snapshot for an agent slug."""

    __tablename__ = "agent_trust_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_slug",
            name="uq_agent_trust_profile",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    agent_slug = Column(String(100), nullable=False)
    trust_score = Column(Float, nullable=False, default=0.5)
    confidence = Column(Float, nullable=False, default=0.0)
    autonomy_tier = Column(String(40), nullable=False, default="recommend_only")
    reward_signal = Column(Float, nullable=False, default=0.5)
    provider_signal = Column(Float, nullable=False, default=0.5)
    rated_experience_count = Column(Integer, nullable=False, default=0)
    provider_review_count = Column(Integer, nullable=False, default=0)
    rationale = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
