import uuid
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, index=True)

    # Default LLM configuration for this tenant
    # use_alter=True resolves circular dependency during DROP TABLE in tests
    default_llm_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("llm_configs.id", name="fk_tenant_default_llm_config", use_alter=True),
        nullable=True
    )

    # Onboarding state (migration 126). Drives `ap quickstart` /
    # `/onboarding` auto-trigger on first authenticated contact. NULL
    # `onboarded_at` means un-onboarded — auto-trigger fires. NULL
    # `onboarding_deferred_at` means user has not pressed Skip; once
    # set, auto-trigger is suppressed but explicit `ap quickstart`
    # still works. See docs/plans/2026-05-11-ap-quickstart-design.md.
    onboarded_at = Column(DateTime, nullable=True)
    onboarding_deferred_at = Column(DateTime, nullable=True)
    onboarding_source = Column(String(32), nullable=True)  # 'cli' | 'web'

    # Relationships
    users = relationship("User", back_populates="tenant")
    branding = relationship("TenantBranding", uselist=False, back_populates="tenant")
    features = relationship("TenantFeatures", uselist=False, back_populates="tenant")
    default_llm_config = relationship("LLMConfig", foreign_keys=[default_llm_config_id])
