import uuid
from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Float, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class AgentTask(Base):
    """Work unit assigned to an agent."""
    __tablename__ = "agent_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("agent_groups.id"), nullable=True)
    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    created_by_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)

    # Task origin
    human_requested = Column(Boolean, default=True)

    # Status tracking
    status = Column(String, default="queued")  # queued, thinking, executing, waiting_input, delegated, reviewing, completed, failed
    priority = Column(String, default="normal")  # critical, high, normal, low, background

    # Task definition
    task_type = Column(String, nullable=True)  # research, analyze, generate, decide, execute
    objective = Column(String, nullable=False)
    context = Column(JSON, nullable=True)  # Input data, conversation history

    # Execution details
    reasoning = Column(JSON, nullable=True)  # Chain of thought
    output = Column(JSON, nullable=True)  # Results
    confidence = Column(Float, nullable=True)  # Agent's confidence 0-1
    error = Column(String, nullable=True)  # Error message if failed

    # Subtask hierarchy
    parent_task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)

    # Approval workflow
    requires_approval = Column(Boolean, default=False)
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Cost tracking
    tokens_used = Column(Integer, default=0)
    cost = Column(Float, default=0.0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # Phase 4 — updated by /api/v1/agents/internal/heartbeat (PostToolUse
    # hook). Migration 122 adds the underlying column.
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    group = relationship("AgentGroup")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    created_by_agent = relationship("Agent", foreign_keys=[created_by_agent_id])
    parent_task = relationship("AgentTask", remote_side=[id])
