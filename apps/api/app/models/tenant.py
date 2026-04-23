import uuid
from sqlalchemy import Column, String, ForeignKey, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)

    # Relationships
    users = relationship("User", back_populates="tenant")
    branding = relationship("TenantBranding", uselist=False, back_populates="tenant")
    features = relationship("TenantFeatures", uselist=False, back_populates="tenant")
