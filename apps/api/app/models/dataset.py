import uuid

from sqlalchemy import Column, String, ForeignKey, Integer, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    source_type = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    storage_uri = Column(String, nullable=True)
    schema = Column(JSON, nullable=True)
    row_count = Column(Integer, default=0)
    sample_rows = Column(JSON, nullable=True)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column(JSON, nullable=True, default=dict)

    tenant = relationship("Tenant")
    connector = relationship("Connector", foreign_keys=[connector_id])
    chat_sessions = relationship("ChatSession", back_populates="dataset", cascade="all, delete-orphan")
