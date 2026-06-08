"""Durable commitment records for tracking agent promises."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class CommitmentRecord(Base):
    """Explicit commitment an agent has made to a user or another agent."""

    __tablename__ = "commitment_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    owner_agent_slug = Column(String(100), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    title = Column(String(500), nullable=False)
    description = Column(Text)
    commitment_type = Column(String(50), nullable=False, default="action")
    state = Column(String(30), nullable=False, default="open")
    priority = Column(String(20), nullable=False, default="normal")

    source_type = Column(String(50), nullable=False, default="tool_call")
    source_ref = Column(JSONB, nullable=False, default=dict)

    due_at = Column(DateTime, nullable=True)
    fulfilled_at = Column(DateTime, nullable=True)
    broken_at = Column(DateTime, nullable=True)
    broken_reason = Column(Text)

    goal_id = Column(UUID(as_uuid=True), ForeignKey("goal_records.id"), nullable=True)
    related_entity_ids = Column(JSONB, nullable=False, default=list)

    # ── Accountable Learning & Commitment System (migration 163) ──────────
    # Proof / risk / escalation / checkpoint spine so the red-flag engine can
    # compute deterministic levels from ledger fields. Additive — see the
    # 2026-06-08 plan §6.
    contract_id = Column(UUID(as_uuid=True), nullable=True)
    proof_required = Column(JSONB, nullable=False, default=list)
    proof_refs = Column(JSONB, nullable=False, default=list)
    stakeholder_refs = Column(JSONB, nullable=False, default=list)
    blocker_refs = Column(JSONB, nullable=False, default=list)
    risk_threshold = Column(String(20), nullable=True)
    escalation_policy = Column(String(30), nullable=True)
    checkpoint_at = Column(DateTime, nullable=True)
    escalation_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    stale_after = Column(DateTime, nullable=True)

    # Multi-agent visibility scoping (migration 087, design doc §7).
    # owner_agent_slug already exists above; visibility/visible_to added here.
    visibility = Column(String(20), nullable=False, default="tenant_wide")
    visible_to = Column(ARRAY(String), nullable=True)

    embedding = Column(Vector(768), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    creator = relationship("User")
    goal = relationship("GoalRecord")
