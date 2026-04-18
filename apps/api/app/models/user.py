import uuid
from sqlalchemy import Boolean, Column, DateTime, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean(), default=True)
    is_superuser = Column(Boolean(), default=False)
    password_reset_token = Column(String, index=True, nullable=True)
    password_reset_expires = Column(DateTime(), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    tenant = relationship("Tenant", back_populates="users")
