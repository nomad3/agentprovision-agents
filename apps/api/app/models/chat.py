import uuid

from sqlalchemy import Column, String, ForeignKey, JSON, DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=True)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=True)
    dataset_group_id = Column(UUID(as_uuid=True), ForeignKey("dataset_groups.id"), nullable=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Orchestration integration
    agent_group_id = Column(UUID(as_uuid=True), ForeignKey("agent_groups.id"), nullable=True)
    root_task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)
    memory_context = Column(JSON, nullable=True)  # {"summary": "...", "key_entities": [...]}

    # Import metadata
    source = Column(String, default="native")  # native, chatgpt_import, claude_import
    external_id = Column(String, nullable=True)  # ID from external system

    dataset = relationship("Dataset", back_populates="chat_sessions")
    dataset_group = relationship("DatasetGroup")
    agent = relationship("Agent", foreign_keys=[agent_id])
    tenant = relationship("Tenant")
    agent_group = relationship("AgentGroup", foreign_keys=[agent_group_id])
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"))
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    context = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Agent integration
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("agent_tasks.id"), nullable=True)

    # Response metadata
    reasoning = Column(String, nullable=True)  # Chain of thought explanation
    confidence = Column(Float, nullable=True)  # 0.0-1.0 confidence score
    tokens_used = Column(Integer, nullable=True)  # Token count for this message

    # Relationships
    session = relationship("ChatSession", back_populates="messages")
    agent = relationship("Agent", foreign_keys=[agent_id])
