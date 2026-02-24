import uuid
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base


class ChannelEvent(Base):
    __tablename__ = "channel_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    channel_account_id = Column(UUID(as_uuid=True), ForeignKey("channel_accounts.id"), nullable=False)
    event_type = Column(String, nullable=False)  # message_inbound, message_outbound, connection_opened, etc.
    direction = Column(String, nullable=True)  # inbound, outbound
    remote_id = Column(String, nullable=True)  # WhatsApp JID
    message_content = Column(String, nullable=True)
    media_url = Column(String, nullable=True)
    chat_session_id = Column(UUID(as_uuid=True), nullable=True)
    agent_id = Column(UUID(as_uuid=True), nullable=True)
    extra_data = Column("metadata", JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant")
    channel_account = relationship("ChannelAccount")
