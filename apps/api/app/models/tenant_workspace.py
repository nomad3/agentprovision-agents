import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class TenantWorkspaceInstall(Base):
    """Tenant-scoped installation state for native workspace packs."""

    __tablename__ = "tenant_workspace_installs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_slug", name="uq_tenant_workspace_install"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_slug = Column(String(96), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="enabled")
    display_order = Column(Integer, nullable=False, default=100)
    pinned = Column(Boolean, nullable=False, default=True)
    config = Column(JSONB, nullable=False, default=dict)
    installed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    installed_version = Column(String(32), nullable=False)
    enabled_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant")
    installer = relationship("User", foreign_keys=[installed_by])


class TenantWorkspaceAuditLog(Base):
    """Audit trail for workspace pack lifecycle transitions."""

    __tablename__ = "tenant_workspace_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_slug = Column(String(96), nullable=False, index=True)
    install_id = Column(UUID(as_uuid=True), ForeignKey("tenant_workspace_installs.id", ondelete="SET NULL"), nullable=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(48), nullable=False)
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    tenant = relationship("Tenant")
    install = relationship("TenantWorkspaceInstall")
    actor = relationship("User", foreign_keys=[actor_user_id])
