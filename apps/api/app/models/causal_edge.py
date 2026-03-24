"""Causal edges linking actions to outcomes in the world model."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class CausalEdge(Base):
    """Directed edge from a cause event to an effect event with confidence."""

    __tablename__ = "causal_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # Cause side
    cause_type = Column(String(50), nullable=False)
    cause_ref = Column(JSONB, nullable=False, default=dict)
    cause_summary = Column(String(500), nullable=False)

    # Effect side
    effect_type = Column(String(50), nullable=False)
    effect_ref = Column(JSONB, nullable=False, default=dict)
    effect_summary = Column(String(500), nullable=False)

    # Causal hypothesis
    confidence = Column(Float, nullable=False, default=0.5)
    mechanism = Column(Text)
    observation_count = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default="hypothesis")

    # Provenance
    source_assertion_id = Column(UUID(as_uuid=True), ForeignKey("world_state_assertions.id"), nullable=True)
    agent_slug = Column(String(100), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    source_assertion = relationship("WorldStateAssertion")
