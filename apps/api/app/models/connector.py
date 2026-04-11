import uuid
from sqlalchemy import Column, String, ForeignKey, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base import Base

class Connector(Base):
    __tablename__ = "connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    type = Column(String, index=True)  # postgres, mysql, s3, gcs, api
    config = Column(JSON)
    status = Column(String, default="pending")  # pending, active, error
    last_test_at = Column(DateTime, nullable=True)
    last_test_error = Column(String, nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    tenant = relationship("Tenant")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
