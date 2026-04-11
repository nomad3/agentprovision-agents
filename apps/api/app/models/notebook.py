import uuid
from sqlalchemy import Column, String, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base

class Notebook(Base):
    __tablename__ = "notebooks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)
    content = Column(JSON)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    metadata_ = Column(JSON, nullable=True, default=dict)  # PostgreSQL metadata
    tenant = relationship("Tenant")
