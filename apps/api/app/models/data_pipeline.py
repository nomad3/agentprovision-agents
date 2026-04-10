import uuid
from sqlalchemy import Column, String, ForeignKey, JSON, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base

class DataPipeline(Base):
    __tablename__ = "data_pipelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)
    config = Column(JSON)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    metadata_ = Column(JSON, nullable=True, default=dict)  # PostgreSQL metadata
    tenant = relationship("Tenant")

    # Scheduling fields
    schedule_type = Column(String)  # cron, interval, manual
    cron_expression = Column(String, nullable=True)  # "0 8 * * MON"
    interval_seconds = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
