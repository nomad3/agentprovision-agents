"""Collaboration session models for structured multi-agent patterns."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class CollaborationSession(Base):
    """A structured multi-agent collaboration following a defined pattern."""

    __tablename__ = "collaboration_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    blackboard_id = Column(UUID(as_uuid=True), ForeignKey("blackboards.id", ondelete="CASCADE"), nullable=False)

    pattern = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="active")
    current_phase = Column(String(50), nullable=False, default="propose")
    phase_index = Column(Integer, nullable=False, default=0)

    # Role assignments
    role_assignments = Column(JSONB, nullable=False, default=dict)
    pattern_config = Column(JSONB, nullable=False, default=dict)

    # Results
    outcome = Column(Text, nullable=True)
    consensus_reached = Column(String(10), nullable=True)
    rounds_completed = Column(Integer, nullable=False, default=0)
    max_rounds = Column(Integer, nullable=False, default=3)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    blackboard = relationship("Blackboard")
