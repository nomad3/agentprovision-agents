# Phase 4: Whitelabel System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable multi-tenant whitelabel customization with branding, feature flags, and analytics.

**Architecture:** Three models (TenantBranding, TenantFeatures, TenantAnalytics) with one-to-one relationship to Tenant. API routes for tenant admins to customize their instance. Industry templates for quick setup.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pydantic schemas

---

## Task 1: Create TenantBranding Model

**Files:**
- Create: `apps/api/app/models/tenant_branding.py`
- Create: `apps/api/app/schemas/tenant_branding.py`
- Create: `apps/api/tests/test_whitelabel.py`
- Modify: `apps/api/app/db/init_db.py` (add import)

**Step 1: Write the failing test**

Create `apps/api/tests/test_whitelabel.py`:

```python
"""Tests for Phase 4: Whitelabel System."""
import pytest
import os

os.environ["TESTING"] = "True"


def test_tenant_branding_model():
    """Test TenantBranding model has required fields."""
    from app.models.tenant_branding import TenantBranding

    assert hasattr(TenantBranding, 'id')
    assert hasattr(TenantBranding, 'tenant_id')
    assert hasattr(TenantBranding, 'company_name')
    assert hasattr(TenantBranding, 'logo_url')
    assert hasattr(TenantBranding, 'logo_dark_url')
    assert hasattr(TenantBranding, 'favicon_url')
    assert hasattr(TenantBranding, 'support_email')
    assert hasattr(TenantBranding, 'primary_color')
    assert hasattr(TenantBranding, 'secondary_color')
    assert hasattr(TenantBranding, 'accent_color')
    assert hasattr(TenantBranding, 'background_color')
    assert hasattr(TenantBranding, 'sidebar_bg')
    assert hasattr(TenantBranding, 'ai_assistant_name')
    assert hasattr(TenantBranding, 'ai_assistant_persona')
    assert hasattr(TenantBranding, 'custom_domain')
    assert hasattr(TenantBranding, 'domain_verified')
    assert hasattr(TenantBranding, 'industry')
    assert hasattr(TenantBranding, 'compliance_mode')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_branding_model -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.models.tenant_branding'"

**Step 3: Write minimal implementation**

Create `apps/api/app/models/tenant_branding.py`:

```python
"""TenantBranding model for whitelabel customization."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, JSON, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class TenantBranding(Base):
    """Tenant branding and whitelabel configuration."""
    __tablename__ = "tenant_branding"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), unique=True, nullable=False)

    # Brand Identity
    company_name = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    logo_dark_url = Column(String, nullable=True)
    favicon_url = Column(String, nullable=True)
    support_email = Column(String, nullable=True)

    # Colors
    primary_color = Column(String, default="#6366f1")  # Indigo
    secondary_color = Column(String, default="#8b5cf6")  # Purple
    accent_color = Column(String, default="#06b6d4")  # Cyan
    background_color = Column(String, default="#0f172a")  # Slate 900
    sidebar_bg = Column(String, default="#1e293b")  # Slate 800

    # AI Customization
    ai_assistant_name = Column(String, default="AI Assistant")
    ai_assistant_persona = Column(JSON, nullable=True)  # personality, tone, style

    # Domain
    custom_domain = Column(String, nullable=True, unique=True)
    domain_verified = Column(Boolean, default=False)
    ssl_certificate_id = Column(String, nullable=True)

    # Industry
    industry = Column(String, nullable=True)  # healthcare, finance, legal, retail
    compliance_mode = Column(JSON, nullable=True)  # ["hipaa", "sox", "gdpr"]

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<TenantBranding {self.company_name or self.tenant_id}>"
```

Create `apps/api/app/schemas/tenant_branding.py`:

```python
"""Pydantic schemas for TenantBranding."""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


class TenantBrandingBase(BaseModel):
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    logo_dark_url: Optional[str] = None
    favicon_url: Optional[str] = None
    support_email: Optional[str] = None
    primary_color: Optional[str] = "#6366f1"
    secondary_color: Optional[str] = "#8b5cf6"
    accent_color: Optional[str] = "#06b6d4"
    background_color: Optional[str] = "#0f172a"
    sidebar_bg: Optional[str] = "#1e293b"
    ai_assistant_name: Optional[str] = "AI Assistant"
    ai_assistant_persona: Optional[Dict[str, Any]] = None
    custom_domain: Optional[str] = None
    industry: Optional[str] = None
    compliance_mode: Optional[List[str]] = None


class TenantBrandingCreate(TenantBrandingBase):
    pass


class TenantBrandingUpdate(BaseModel):
    company_name: Optional[str] = None
    logo_url: Optional[str] = None
    logo_dark_url: Optional[str] = None
    favicon_url: Optional[str] = None
    support_email: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    background_color: Optional[str] = None
    sidebar_bg: Optional[str] = None
    ai_assistant_name: Optional[str] = None
    ai_assistant_persona: Optional[Dict[str, Any]] = None
    custom_domain: Optional[str] = None
    industry: Optional[str] = None
    compliance_mode: Optional[List[str]] = None


class TenantBranding(TenantBrandingBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    domain_verified: bool = False
    ssl_certificate_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

**Step 4: Update init_db.py**

Add to `apps/api/app/db/init_db.py` after line 27:

```python
from app.models.tenant_branding import TenantBranding  # noqa: F401
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_branding_model -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/models/tenant_branding.py apps/api/app/schemas/tenant_branding.py apps/api/tests/test_whitelabel.py apps/api/app/db/init_db.py
git commit -m "feat(whitelabel): add TenantBranding model for customization"
```

---

## Task 2: Create TenantFeatures Model

**Files:**
- Create: `apps/api/app/models/tenant_features.py`
- Create: `apps/api/app/schemas/tenant_features.py`
- Modify: `apps/api/tests/test_whitelabel.py` (add test)
- Modify: `apps/api/app/db/init_db.py` (add import)

**Step 1: Write the failing test**

Add to `apps/api/tests/test_whitelabel.py`:

```python
def test_tenant_features_model():
    """Test TenantFeatures model has required fields."""
    from app.models.tenant_features import TenantFeatures

    assert hasattr(TenantFeatures, 'id')
    assert hasattr(TenantFeatures, 'tenant_id')
    # Core Features
    assert hasattr(TenantFeatures, 'agents_enabled')
    assert hasattr(TenantFeatures, 'agent_groups_enabled')
    assert hasattr(TenantFeatures, 'datasets_enabled')
    assert hasattr(TenantFeatures, 'chat_enabled')
    assert hasattr(TenantFeatures, 'multi_llm_enabled')
    assert hasattr(TenantFeatures, 'agent_memory_enabled')
    # AI Intelligence
    assert hasattr(TenantFeatures, 'ai_insights_enabled')
    assert hasattr(TenantFeatures, 'ai_recommendations_enabled')
    assert hasattr(TenantFeatures, 'ai_anomaly_detection')
    # Limits
    assert hasattr(TenantFeatures, 'max_agents')
    assert hasattr(TenantFeatures, 'max_agent_groups')
    assert hasattr(TenantFeatures, 'monthly_token_limit')
    assert hasattr(TenantFeatures, 'storage_limit_gb')
    # UI
    assert hasattr(TenantFeatures, 'hide_agentprovision_branding')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_features_model -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

Create `apps/api/app/models/tenant_features.py`:

```python
"""TenantFeatures model for feature flags and limits."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class TenantFeatures(Base):
    """Tenant feature flags and usage limits."""
    __tablename__ = "tenant_features"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), unique=True, nullable=False)

    # Core Features
    agents_enabled = Column(Boolean, default=True)
    agent_groups_enabled = Column(Boolean, default=True)
    datasets_enabled = Column(Boolean, default=True)
    chat_enabled = Column(Boolean, default=True)
    multi_llm_enabled = Column(Boolean, default=True)
    agent_memory_enabled = Column(Boolean, default=True)

    # AI Intelligence Features
    ai_insights_enabled = Column(Boolean, default=True)
    ai_recommendations_enabled = Column(Boolean, default=True)
    ai_anomaly_detection = Column(Boolean, default=True)

    # Usage Limits
    max_agents = Column(Integer, default=10)
    max_agent_groups = Column(Integer, default=5)
    monthly_token_limit = Column(Integer, default=1000000)
    storage_limit_gb = Column(Float, default=10.0)

    # UI Customization
    hide_agentprovision_branding = Column(Boolean, default=False)

    # Plan Type
    plan_type = Column(String, default="starter")  # starter, professional, enterprise

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<TenantFeatures {self.tenant_id} plan={self.plan_type}>"
```

Create `apps/api/app/schemas/tenant_features.py`:

```python
"""Pydantic schemas for TenantFeatures."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class TenantFeaturesBase(BaseModel):
    # Core Features
    agents_enabled: bool = True
    agent_groups_enabled: bool = True
    datasets_enabled: bool = True
    chat_enabled: bool = True
    multi_llm_enabled: bool = True
    agent_memory_enabled: bool = True
    # AI Intelligence
    ai_insights_enabled: bool = True
    ai_recommendations_enabled: bool = True
    ai_anomaly_detection: bool = True
    # Limits
    max_agents: int = 10
    max_agent_groups: int = 5
    monthly_token_limit: int = 1000000
    storage_limit_gb: float = 10.0
    # UI
    hide_agentprovision_branding: bool = False
    plan_type: str = "starter"


class TenantFeaturesCreate(TenantFeaturesBase):
    pass


class TenantFeaturesUpdate(BaseModel):
    agents_enabled: Optional[bool] = None
    agent_groups_enabled: Optional[bool] = None
    datasets_enabled: Optional[bool] = None
    chat_enabled: Optional[bool] = None
    multi_llm_enabled: Optional[bool] = None
    agent_memory_enabled: Optional[bool] = None
    ai_insights_enabled: Optional[bool] = None
    ai_recommendations_enabled: Optional[bool] = None
    ai_anomaly_detection: Optional[bool] = None
    max_agents: Optional[int] = None
    max_agent_groups: Optional[int] = None
    monthly_token_limit: Optional[int] = None
    storage_limit_gb: Optional[float] = None
    hide_agentprovision_branding: Optional[bool] = None
    plan_type: Optional[str] = None


class TenantFeatures(TenantFeaturesBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

**Step 4: Update init_db.py**

Add to `apps/api/app/db/init_db.py` after tenant_branding import:

```python
from app.models.tenant_features import TenantFeatures  # noqa: F401
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_features_model -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/models/tenant_features.py apps/api/app/schemas/tenant_features.py apps/api/tests/test_whitelabel.py apps/api/app/db/init_db.py
git commit -m "feat(whitelabel): add TenantFeatures model for feature flags"
```

---

## Task 3: Create TenantAnalytics Model

**Files:**
- Create: `apps/api/app/models/tenant_analytics.py`
- Create: `apps/api/app/schemas/tenant_analytics.py`
- Modify: `apps/api/tests/test_whitelabel.py` (add test)
- Modify: `apps/api/app/db/init_db.py` (add import)

**Step 1: Write the failing test**

Add to `apps/api/tests/test_whitelabel.py`:

```python
def test_tenant_analytics_model():
    """Test TenantAnalytics model has required fields."""
    from app.models.tenant_analytics import TenantAnalytics

    assert hasattr(TenantAnalytics, 'id')
    assert hasattr(TenantAnalytics, 'tenant_id')
    assert hasattr(TenantAnalytics, 'period')
    assert hasattr(TenantAnalytics, 'period_start')
    # Usage Metrics
    assert hasattr(TenantAnalytics, 'total_messages')
    assert hasattr(TenantAnalytics, 'total_tasks')
    assert hasattr(TenantAnalytics, 'total_tokens_used')
    assert hasattr(TenantAnalytics, 'total_cost')
    # AI-Generated
    assert hasattr(TenantAnalytics, 'ai_insights')
    assert hasattr(TenantAnalytics, 'ai_recommendations')
    assert hasattr(TenantAnalytics, 'ai_forecast')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_analytics_model -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

Create `apps/api/app/models/tenant_analytics.py`:

```python
"""TenantAnalytics model for usage tracking and AI insights."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class TenantAnalytics(Base):
    """Tenant usage analytics and AI-generated insights."""
    __tablename__ = "tenant_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    period = Column(String, nullable=False)  # hourly, daily, weekly, monthly
    period_start = Column(DateTime, nullable=False, index=True)

    # Usage Metrics
    total_messages = Column(Integer, default=0)
    total_tasks = Column(Integer, default=0)
    total_tokens_used = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)

    # Agent Metrics
    active_agents = Column(Integer, default=0)
    tasks_completed = Column(Integer, default=0)
    tasks_failed = Column(Integer, default=0)
    avg_task_duration_seconds = Column(Float, nullable=True)

    # AI-Generated Insights
    ai_insights = Column(JSON, nullable=True)  # Key findings from the period
    ai_recommendations = Column(JSON, nullable=True)  # Suggested improvements
    ai_forecast = Column(JSON, nullable=True)  # Predicted usage trends

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TenantAnalytics {self.tenant_id} {self.period} {self.period_start}>"
```

Create `apps/api/app/schemas/tenant_analytics.py`:

```python
"""Pydantic schemas for TenantAnalytics."""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


class TenantAnalyticsBase(BaseModel):
    period: str  # hourly, daily, weekly, monthly
    period_start: datetime
    total_messages: int = 0
    total_tasks: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0
    active_agents: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_task_duration_seconds: Optional[float] = None
    ai_insights: Optional[Dict[str, Any]] = None
    ai_recommendations: Optional[List[str]] = None
    ai_forecast: Optional[Dict[str, Any]] = None


class TenantAnalyticsCreate(TenantAnalyticsBase):
    pass


class TenantAnalytics(TenantAnalyticsBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True


class TenantAnalyticsSummary(BaseModel):
    """Summary of tenant analytics for dashboard."""
    current_period: Optional[TenantAnalytics] = None
    previous_period: Optional[TenantAnalytics] = None
    token_usage_percentage: float = 0.0
    storage_usage_percentage: float = 0.0
    top_agents: List[Dict[str, Any]] = []
    recent_insights: List[str] = []
```

**Step 4: Update init_db.py**

Add to `apps/api/app/db/init_db.py` after tenant_features import:

```python
from app.models.tenant_analytics import TenantAnalytics  # noqa: F401
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_analytics_model -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/models/tenant_analytics.py apps/api/app/schemas/tenant_analytics.py apps/api/tests/test_whitelabel.py apps/api/app/db/init_db.py
git commit -m "feat(whitelabel): add TenantAnalytics model for usage tracking"
```

---

## Task 4: Create Branding API Routes

**Files:**
- Create: `apps/api/app/services/branding.py`
- Create: `apps/api/app/api/v1/branding.py`
- Modify: `apps/api/app/api/v1/routes.py` (register router)
- Modify: `apps/api/tests/test_whitelabel.py` (add test)

**Step 1: Write the failing test**

Add to `apps/api/tests/test_whitelabel.py`:

```python
def test_branding_api_routes():
    """Test branding API routes exist."""
    from app.api.v1 import branding

    assert hasattr(branding, 'router')
    assert hasattr(branding, 'get_branding')
    assert hasattr(branding, 'update_branding')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_branding_api_routes -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

Create `apps/api/app/services/branding.py`:

```python
"""Branding service for tenant whitelabel management."""
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from app.models.tenant_branding import TenantBranding
from app.schemas.tenant_branding import TenantBrandingCreate, TenantBrandingUpdate


def get_branding(db: Session, tenant_id: uuid.UUID) -> Optional[TenantBranding]:
    """Get tenant branding by tenant_id."""
    return db.query(TenantBranding).filter(
        TenantBranding.tenant_id == tenant_id
    ).first()


def create_branding(
    db: Session,
    tenant_id: uuid.UUID,
    branding_in: TenantBrandingCreate
) -> TenantBranding:
    """Create tenant branding."""
    branding = TenantBranding(
        tenant_id=tenant_id,
        **branding_in.model_dump(exclude_unset=True)
    )
    db.add(branding)
    db.commit()
    db.refresh(branding)
    return branding


def update_branding(
    db: Session,
    tenant_id: uuid.UUID,
    branding_in: TenantBrandingUpdate
) -> Optional[TenantBranding]:
    """Update tenant branding."""
    branding = get_branding(db, tenant_id)
    if not branding:
        return None

    update_data = branding_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(branding, field, value)

    db.add(branding)
    db.commit()
    db.refresh(branding)
    return branding


def get_or_create_branding(
    db: Session,
    tenant_id: uuid.UUID
) -> TenantBranding:
    """Get existing branding or create with defaults."""
    branding = get_branding(db, tenant_id)
    if not branding:
        branding = create_branding(db, tenant_id, TenantBrandingCreate())
    return branding


def verify_custom_domain(
    db: Session,
    tenant_id: uuid.UUID,
    domain: str
) -> bool:
    """Verify custom domain ownership (placeholder for DNS verification)."""
    branding = get_branding(db, tenant_id)
    if branding and branding.custom_domain == domain:
        branding.domain_verified = True
        db.commit()
        return True
    return False
```

Create `apps/api/app/api/v1/branding.py`:

```python
"""API routes for tenant branding."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.tenant_branding import TenantBranding, TenantBrandingUpdate
from app.services import branding as service

router = APIRouter()


@router.get("", response_model=TenantBranding)
def get_branding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current tenant's branding configuration."""
    branding = service.get_or_create_branding(db, current_user.tenant_id)
    return branding


@router.put("", response_model=TenantBranding)
def update_branding(
    branding_in: TenantBrandingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update current tenant's branding configuration."""
    # Ensure branding exists
    service.get_or_create_branding(db, current_user.tenant_id)
    branding = service.update_branding(db, current_user.tenant_id, branding_in)
    return branding


@router.post("/verify-domain", response_model=dict)
def verify_domain(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Verify custom domain ownership."""
    branding = service.get_branding(db, current_user.tenant_id)
    if not branding or not branding.custom_domain:
        raise HTTPException(status_code=400, detail="No custom domain configured")

    # In production, this would check DNS records
    success = service.verify_custom_domain(
        db, current_user.tenant_id, branding.custom_domain
    )
    return {"verified": success, "domain": branding.custom_domain}
```

**Step 4: Update routes.py**

Add to imports in `apps/api/app/api/v1/routes.py`:

```python
    branding,
```

Add router registration:

```python
router.include_router(branding.router, prefix="/branding", tags=["branding"])
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_branding_api_routes -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/services/branding.py apps/api/app/api/v1/branding.py apps/api/app/api/v1/routes.py apps/api/tests/test_whitelabel.py
git commit -m "feat(whitelabel): add Branding API routes"
```

---

## Task 5: Create Features API Routes

**Files:**
- Create: `apps/api/app/services/features.py`
- Create: `apps/api/app/api/v1/features.py`
- Modify: `apps/api/app/api/v1/routes.py` (register router)
- Modify: `apps/api/tests/test_whitelabel.py` (add test)

**Step 1: Write the failing test**

Add to `apps/api/tests/test_whitelabel.py`:

```python
def test_features_api_routes():
    """Test features API routes exist."""
    from app.api.v1 import features

    assert hasattr(features, 'router')
    assert hasattr(features, 'get_features')
    assert hasattr(features, 'check_feature')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_features_api_routes -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `apps/api/app/services/features.py`:

```python
"""Feature flags service for tenant feature management."""
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from app.models.tenant_features import TenantFeatures
from app.schemas.tenant_features import TenantFeaturesCreate, TenantFeaturesUpdate


def get_features(db: Session, tenant_id: uuid.UUID) -> Optional[TenantFeatures]:
    """Get tenant features by tenant_id."""
    return db.query(TenantFeatures).filter(
        TenantFeatures.tenant_id == tenant_id
    ).first()


def create_features(
    db: Session,
    tenant_id: uuid.UUID,
    features_in: TenantFeaturesCreate
) -> TenantFeatures:
    """Create tenant features."""
    features = TenantFeatures(
        tenant_id=tenant_id,
        **features_in.model_dump(exclude_unset=True)
    )
    db.add(features)
    db.commit()
    db.refresh(features)
    return features


def update_features(
    db: Session,
    tenant_id: uuid.UUID,
    features_in: TenantFeaturesUpdate
) -> Optional[TenantFeatures]:
    """Update tenant features."""
    features = get_features(db, tenant_id)
    if not features:
        return None

    update_data = features_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(features, field, value)

    db.add(features)
    db.commit()
    db.refresh(features)
    return features


def get_or_create_features(
    db: Session,
    tenant_id: uuid.UUID
) -> TenantFeatures:
    """Get existing features or create with defaults."""
    features = get_features(db, tenant_id)
    if not features:
        features = create_features(db, tenant_id, TenantFeaturesCreate())
    return features


def is_feature_enabled(
    db: Session,
    tenant_id: uuid.UUID,
    feature_name: str
) -> bool:
    """Check if a specific feature is enabled for tenant."""
    features = get_or_create_features(db, tenant_id)
    return getattr(features, feature_name, False)


def check_limit(
    db: Session,
    tenant_id: uuid.UUID,
    limit_name: str,
    current_usage: int
) -> bool:
    """Check if current usage is within limits."""
    features = get_or_create_features(db, tenant_id)
    limit_value = getattr(features, limit_name, None)
    if limit_value is None:
        return True
    return current_usage < limit_value
```

Create `apps/api/app/api/v1/features.py`:

```python
"""API routes for tenant features."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.tenant_features import TenantFeatures, TenantFeaturesUpdate
from app.services import features as service

router = APIRouter()


@router.get("", response_model=TenantFeatures)
def get_features(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current tenant's feature flags and limits."""
    features = service.get_or_create_features(db, current_user.tenant_id)
    return features


@router.put("", response_model=TenantFeatures)
def update_features(
    features_in: TenantFeaturesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update current tenant's feature flags (admin only in production)."""
    # Ensure features exist
    service.get_or_create_features(db, current_user.tenant_id)
    features = service.update_features(db, current_user.tenant_id, features_in)
    return features


@router.get("/check/{feature_name}", response_model=Dict[str, bool])
def check_feature(
    feature_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check if a specific feature is enabled."""
    enabled = service.is_feature_enabled(db, current_user.tenant_id, feature_name)
    return {"feature": feature_name, "enabled": enabled}


@router.get("/limits", response_model=Dict[str, dict])
def get_limits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current tenant's usage limits."""
    features = service.get_or_create_features(db, current_user.tenant_id)
    return {
        "max_agents": {"limit": features.max_agents},
        "max_agent_groups": {"limit": features.max_agent_groups},
        "monthly_token_limit": {"limit": features.monthly_token_limit},
        "storage_limit_gb": {"limit": features.storage_limit_gb},
    }
```

**Step 4: Update routes.py**

Add to imports:

```python
    features,
```

Add router registration:

```python
router.include_router(features.router, prefix="/features", tags=["features"])
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_features_api_routes -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/services/features.py apps/api/app/api/v1/features.py apps/api/app/api/v1/routes.py apps/api/tests/test_whitelabel.py
git commit -m "feat(whitelabel): add Features API routes"
```

---

## Task 6: Create Tenant Analytics API Routes

**Files:**
- Create: `apps/api/app/services/tenant_analytics.py`
- Create: `apps/api/app/api/v1/tenant_analytics.py`
- Modify: `apps/api/app/api/v1/routes.py` (register router)
- Modify: `apps/api/tests/test_whitelabel.py` (add test)

**Step 1: Write the failing test**

Add to `apps/api/tests/test_whitelabel.py`:

```python
def test_tenant_analytics_api_routes():
    """Test tenant analytics API routes exist."""
    from app.api.v1 import tenant_analytics

    assert hasattr(tenant_analytics, 'router')
    assert hasattr(tenant_analytics, 'get_analytics_summary')
    assert hasattr(tenant_analytics, 'get_analytics_history')
```

**Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_analytics_api_routes -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Create `apps/api/app/services/tenant_analytics.py`:

```python
"""Tenant analytics service for usage tracking."""
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timedelta
import uuid

from app.models.tenant_analytics import TenantAnalytics
from app.models.chat import ChatMessage
from app.models.agent_task import AgentTask
from app.schemas.tenant_analytics import TenantAnalyticsCreate, TenantAnalyticsSummary


def get_analytics(
    db: Session,
    tenant_id: uuid.UUID,
    period: str,
    period_start: datetime
) -> Optional[TenantAnalytics]:
    """Get analytics for a specific period."""
    return db.query(TenantAnalytics).filter(
        TenantAnalytics.tenant_id == tenant_id,
        TenantAnalytics.period == period,
        TenantAnalytics.period_start == period_start
    ).first()


def get_analytics_history(
    db: Session,
    tenant_id: uuid.UUID,
    period: str = "daily",
    limit: int = 30
) -> List[TenantAnalytics]:
    """Get analytics history for a tenant."""
    return db.query(TenantAnalytics).filter(
        TenantAnalytics.tenant_id == tenant_id,
        TenantAnalytics.period == period
    ).order_by(TenantAnalytics.period_start.desc()).limit(limit).all()


def create_analytics(
    db: Session,
    tenant_id: uuid.UUID,
    analytics_in: TenantAnalyticsCreate
) -> TenantAnalytics:
    """Create analytics record."""
    analytics = TenantAnalytics(
        tenant_id=tenant_id,
        **analytics_in.model_dump()
    )
    db.add(analytics)
    db.commit()
    db.refresh(analytics)
    return analytics


def calculate_period_analytics(
    db: Session,
    tenant_id: uuid.UUID,
    period: str,
    period_start: datetime
) -> TenantAnalytics:
    """Calculate analytics for a period."""
    if period == "daily":
        period_end = period_start + timedelta(days=1)
    elif period == "weekly":
        period_end = period_start + timedelta(weeks=1)
    elif period == "monthly":
        period_end = period_start + timedelta(days=30)
    else:  # hourly
        period_end = period_start + timedelta(hours=1)

    # Count messages in period (simplified - in production would filter by tenant)
    total_messages = db.query(func.count(ChatMessage.id)).scalar() or 0

    # Count tasks
    total_tasks = db.query(func.count(AgentTask.id)).filter(
        AgentTask.created_at >= period_start,
        AgentTask.created_at < period_end
    ).scalar() or 0

    analytics_data = TenantAnalyticsCreate(
        period=period,
        period_start=period_start,
        total_messages=total_messages,
        total_tasks=total_tasks,
        total_tokens_used=0,  # Would calculate from usage tracking
        total_cost=0.0,
    )

    # Check if exists and update, or create new
    existing = get_analytics(db, tenant_id, period, period_start)
    if existing:
        for field, value in analytics_data.model_dump().items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
        return existing

    return create_analytics(db, tenant_id, analytics_data)


def get_analytics_summary(
    db: Session,
    tenant_id: uuid.UUID
) -> TenantAnalyticsSummary:
    """Get analytics summary for dashboard."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    current = get_analytics(db, tenant_id, "daily", today)
    previous = get_analytics(db, tenant_id, "daily", yesterday)

    return TenantAnalyticsSummary(
        current_period=current,
        previous_period=previous,
        token_usage_percentage=0.0,  # Would calculate from features
        storage_usage_percentage=0.0,
        top_agents=[],
        recent_insights=[]
    )
```

Create `apps/api/app/api/v1/tenant_analytics.py`:

```python
"""API routes for tenant analytics."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.tenant_analytics import TenantAnalytics, TenantAnalyticsSummary
from app.services import tenant_analytics as service

router = APIRouter()


@router.get("/summary", response_model=TenantAnalyticsSummary)
def get_analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get analytics summary for dashboard."""
    return service.get_analytics_summary(db, current_user.tenant_id)


@router.get("/history", response_model=List[TenantAnalytics])
def get_analytics_history(
    period: str = "daily",
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get analytics history."""
    return service.get_analytics_history(
        db, current_user.tenant_id, period, limit
    )


@router.post("/calculate", response_model=TenantAnalytics)
def calculate_analytics(
    period: str = "daily",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Calculate and store analytics for current period."""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return service.calculate_period_analytics(
        db, current_user.tenant_id, period, today
    )
```

**Step 4: Update routes.py**

Add to imports:

```python
    tenant_analytics,
```

Add router registration:

```python
router.include_router(tenant_analytics.router, prefix="/tenant-analytics", tags=["tenant-analytics"])
```

**Step 5: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_whitelabel.py::test_tenant_analytics_api_routes -v`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/app/services/tenant_analytics.py apps/api/app/api/v1/tenant_analytics.py apps/api/app/api/v1/routes.py apps/api/tests/test_whitelabel.py
git commit -m "feat(whitelabel): add Tenant Analytics API routes"
```

---

## Task 7: Run All Tests and Final Commit

**Step 1: Run all whitelabel tests**

Run: `cd apps/api && pytest tests/test_whitelabel.py -v`
Expected: All 6 tests PASS

**Step 2: Run full test suite**

Run: `cd apps/api && pytest tests/ -v --tb=short`
Expected: All tests pass

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat(whitelabel): complete Phase 4 - Whitelabel System

- TenantBranding: logo, colors, custom domain, AI assistant persona
- TenantFeatures: feature flags, usage limits, plan types
- TenantAnalytics: usage metrics, AI-generated insights
- API routes: /branding, /features, /tenant-analytics
- Services: branding, features, tenant_analytics"
```

---

## Summary

Phase 4 adds:
- **3 Models**: TenantBranding, TenantFeatures, TenantAnalytics
- **3 Services**: branding.py, features.py, tenant_analytics.py
- **3 API Routes**: /api/v1/branding, /api/v1/features, /api/v1/tenant-analytics
- **6 Tests**: Model and route tests

Endpoints created:
- `GET/PUT /api/v1/branding` - Tenant branding
- `POST /api/v1/branding/verify-domain` - Domain verification
- `GET/PUT /api/v1/features` - Feature flags
- `GET /api/v1/features/check/{name}` - Check feature
- `GET /api/v1/features/limits` - Usage limits
- `GET /api/v1/tenant-analytics/summary` - Dashboard summary
- `GET /api/v1/tenant-analytics/history` - Historical data
- `POST /api/v1/tenant-analytics/calculate` - Trigger calculation
