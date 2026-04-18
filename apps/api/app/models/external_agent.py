import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base import Base


class ExternalAgent(Base):
    __tablename__ = "external_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)

    # Connection
    protocol = Column(String, nullable=False)  # openai_chat|mcp_sse|webhook|a2a|copilot_extension
    endpoint_url = Column(String, nullable=False)
    auth_type = Column(String, nullable=False, default="bearer")  # bearer|api_key|hmac|github_app
    credential_id = Column(UUID(as_uuid=True), ForeignKey("integration_credentials.id", ondelete="SET NULL"), nullable=True)

    # Capabilities
    capabilities = Column(JSONB, nullable=False, default=list)  # ["code","search","data_analysis",...]

    # Health
    health_check_path = Column(String, nullable=False, default="/health")
    status = Column(String, nullable=False, default="offline")  # online|offline|busy|error
    last_seen_at = Column(DateTime, nullable=True)

    # Stats
    task_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    avg_latency_ms = Column(Integer, nullable=True)

    # Protocol-specific config (model name, max_tokens, timeout, etc.)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    credential = relationship("IntegrationCredential", foreign_keys=[credential_id])
