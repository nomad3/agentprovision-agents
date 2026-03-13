# Reinforcement Learning Framework Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Reward-Weighted Experience Store (RWES) reinforcement learning framework that learns from every platform decision and improves over time, with a dedicated Learning page for visualization and management.

**Architecture:** Every decision point (agent selection, memory recall, skill routing, etc.) logs experiences with state embeddings (Gemini Embedding 2, 768-dim via pgvector). Rewards flow from implicit signals, explicit user feedback, and admin reviews. A policy engine scores candidates using reward-weighted regression over similar past experiences. Federated learning provides a global baseline with per-tenant fine-tuning.

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy, Temporal), PostgreSQL + pgvector, Gemini Embedding 2 (768-dim), React 18 + Bootstrap 5 + i18next, existing embedding_service infrastructure.

**Design Spec:** `docs/plans/2026-03-12-reinforcement-learning-framework-design.md`

---

## Chunk 1: Data Foundation (Models, Schemas, Migration)

### Task 1: Database Migration — RL Tables + Notification updated_at

**Files:**
- Create: `apps/api/migrations/045_add_rl_framework.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 045_add_rl_framework.sql
-- Reinforcement Learning Framework tables

-- Enable pgvector if not already
CREATE EXTENSION IF NOT EXISTS vector;

-- RL Experiences table
CREATE TABLE IF NOT EXISTS rl_experiences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    trajectory_id UUID NOT NULL,
    step_index INTEGER NOT NULL DEFAULT 0,
    decision_point VARCHAR(50) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}',
    state_embedding vector(768),
    action JSONB NOT NULL DEFAULT '{}',
    alternatives JSONB DEFAULT '[]',
    reward FLOAT,
    reward_components JSONB,
    reward_source VARCHAR(50),
    explanation JSONB,
    policy_version VARCHAR(50),
    exploration BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    rewarded_at TIMESTAMP,
    archived_at TIMESTAMP
);

-- Indexes for rl_experiences
CREATE INDEX idx_rl_exp_tenant_dp_created
    ON rl_experiences (tenant_id, decision_point, created_at DESC);
CREATE INDEX idx_rl_exp_trajectory
    ON rl_experiences (trajectory_id);
CREATE INDEX idx_rl_exp_tenant_archived
    ON rl_experiences (tenant_id, archived_at)
    WHERE archived_at IS NULL;

-- HNSW index for state_embedding similarity search
-- Using HNSW instead of IVFFlat because IVFFlat requires data to build clusters.
-- Since rl_experiences starts empty, HNSW works correctly from zero rows.
CREATE INDEX idx_rl_exp_state_embedding
    ON rl_experiences
    USING hnsw (state_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- RL Policy States table
CREATE TABLE IF NOT EXISTS rl_policy_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    decision_point VARCHAR(50) NOT NULL,
    weights JSONB NOT NULL DEFAULT '{}',
    version VARCHAR(50) NOT NULL DEFAULT 'v1',
    experience_count INTEGER NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    exploration_rate FLOAT NOT NULL DEFAULT 0.1
);

-- Unique constraint: one policy per tenant per decision point
CREATE UNIQUE INDEX idx_rl_policy_tenant_dp
    ON rl_policy_states (tenant_id, decision_point)
    WHERE tenant_id IS NOT NULL;

-- Global baseline: one per decision point where tenant_id IS NULL
CREATE UNIQUE INDEX idx_rl_policy_global_dp
    ON rl_policy_states (decision_point)
    WHERE tenant_id IS NULL;

-- Add rl_settings JSON column to tenant_features
ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS rl_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rl_settings JSONB NOT NULL DEFAULT '{
        "exploration_rate": 0.1,
        "opt_in_global_learning": true,
        "use_global_baseline": true,
        "min_tenant_experiences": 50,
        "blend_alpha_growth": 0.01,
        "reward_weights": {"implicit": 0.3, "explicit": 0.5, "admin": 0.2},
        "review_schedule": "weekly",
        "per_decision_overrides": {}
    }';

-- Add updated_at to notifications (prerequisite for implicit reward signals)
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
```

- [ ] **Step 2: Run the migration**

Run: `docker-compose exec db psql -U postgres servicetsunami -f /dev/stdin < apps/api/migrations/045_add_rl_framework.sql`
Expected: Tables created, indexes added, columns altered. No errors.

- [ ] **Step 3: Verify tables exist**

Run: `docker-compose exec db psql -U postgres servicetsunami -c "\dt rl_*"`
Expected: `rl_experiences` and `rl_policy_states` tables listed.

- [ ] **Step 4: Commit**

```bash
git add apps/api/migrations/045_add_rl_framework.sql
git commit -m "feat: add RL framework database migration (experiences, policy states, tenant settings)"
```

---

### Task 2: RLExperience Model

**Files:**
- Create: `apps/api/app/models/rl_experience.py`

- [ ] **Step 1: Create the model file**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from app.db.base import Base


class RLExperience(Base):
    __tablename__ = "rl_experiences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    trajectory_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    step_index = Column(Integer, nullable=False, default=0)
    decision_point = Column(String(50), nullable=False, index=True)
    state = Column(JSONB, nullable=False, default=dict)
    state_embedding = Column(Vector(768))
    action = Column(JSONB, nullable=False, default=dict)
    alternatives = Column(JSONB, default=list)
    reward = Column(Float, nullable=True)
    reward_components = Column(JSONB)
    reward_source = Column(String(50))
    explanation = Column(JSONB)
    policy_version = Column(String(50))
    exploration = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    rewarded_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
```

- [ ] **Step 2: Verify model imports work**

Run: `cd apps/api && python -c "from app.models.rl_experience import RLExperience; print(RLExperience.__tablename__)"`
Expected: `rl_experiences`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/models/rl_experience.py
git commit -m "feat: add RLExperience model"
```

---

### Task 3: RLPolicyState Model

**Files:**
- Create: `apps/api/app/models/rl_policy_state.py`

- [ ] **Step 1: Create the model file**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base


class RLPolicyState(Base):
    __tablename__ = "rl_policy_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    decision_point = Column(String(50), nullable=False)
    weights = Column(JSONB, nullable=False, default=dict)
    version = Column(String(50), nullable=False, default="v1")
    experience_count = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    exploration_rate = Column(Float, nullable=False, default=0.1)
```

- [ ] **Step 2: Verify model imports work**

Run: `cd apps/api && python -c "from app.models.rl_policy_state import RLPolicyState; print(RLPolicyState.__tablename__)"`
Expected: `rl_policy_states`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/models/rl_policy_state.py
git commit -m "feat: add RLPolicyState model"
```

---

### Task 4: Register Models in __init__.py + Update Existing Models

**Files:**
- Modify: `apps/api/app/models/__init__.py:23` (add imports near existing Embedding import)
- Modify: `apps/api/app/models/tenant_features.py:29` (add rl_enabled and rl_settings columns)
- Modify: `apps/api/app/models/notification.py:29` (add updated_at column)

- [ ] **Step 1: Add model imports to `__init__.py`**

Add after the Embedding import (line 23):
```python
from .rl_experience import RLExperience
from .rl_policy_state import RLPolicyState
```

Add to `__all__` list (after existing entries):
```python
"RLExperience",
"RLPolicyState",
```

- [ ] **Step 2: Add rl_enabled and rl_settings to `tenant_features.py`**

Add after `ai_anomaly_detection = Column(Boolean, default=True)` (line 29):
```python
    rl_enabled = Column(Boolean, default=False)
    rl_settings = Column(JSONB, nullable=False, default=lambda: {
        "exploration_rate": 0.1,
        "opt_in_global_learning": True,
        "use_global_baseline": True,
        "min_tenant_experiences": 50,
        "blend_alpha_growth": 0.01,
        "reward_weights": {"implicit": 0.3, "explicit": 0.5, "admin": 0.2},
        "review_schedule": "weekly",
        "per_decision_overrides": {}
    })
```

Add `JSONB` to the `sqlalchemy.dialects.postgresql` import line (not the main `sqlalchemy` import):
```python
from sqlalchemy.dialects.postgresql import UUID, JSONB
```

- [ ] **Step 3: Add updated_at to `notification.py`**

Add after `created_at` column (line 29):
```python
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 4: Update existing Pydantic schemas**

Update `apps/api/app/schemas/tenant_features.py` — add to the base/response schema:
```python
    rl_enabled: bool = False
    rl_settings: Optional[Dict[str, Any]] = None
```

Update `apps/api/app/schemas/notification.py` — add to `NotificationInDB`:
```python
    updated_at: Optional[datetime] = None
```

- [ ] **Step 5: Verify all models load together**

Run: `cd apps/api && python -c "from app.models import RLExperience, RLPolicyState; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/models/__init__.py apps/api/app/models/tenant_features.py apps/api/app/models/notification.py apps/api/app/schemas/tenant_features.py apps/api/app/schemas/notification.py
git commit -m "feat: register RL models, add rl_settings to tenant features, add updated_at to notifications"
```

---

### Task 5: Pydantic Schemas

**Files:**
- Create: `apps/api/app/schemas/rl_experience.py`
- Create: `apps/api/app/schemas/rl_policy_state.py`

- [ ] **Step 1: Create RL experience schemas**

```python
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class RLExperienceCreate(BaseModel):
    trajectory_id: uuid.UUID
    step_index: int = 0
    decision_point: str
    state: Dict[str, Any] = {}
    action: Dict[str, Any] = {}
    alternatives: List[Dict[str, Any]] = []
    explanation: Optional[Dict[str, Any]] = None
    policy_version: Optional[str] = None
    exploration: bool = False


class RLExperienceInDB(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    trajectory_id: uuid.UUID
    step_index: int
    decision_point: str
    state: Dict[str, Any]
    action: Dict[str, Any]
    alternatives: List[Dict[str, Any]]
    reward: Optional[float] = None
    reward_components: Optional[Dict[str, Any]] = None
    reward_source: Optional[str] = None
    explanation: Optional[Dict[str, Any]] = None
    policy_version: Optional[str] = None
    exploration: bool
    created_at: datetime
    rewarded_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RLExperienceWithReward(RLExperienceInDB):
    similarity: Optional[float] = None


class RLFeedbackSubmit(BaseModel):
    trajectory_id: uuid.UUID
    step_index: Optional[int] = None
    feedback_type: str  # thumbs_up, thumbs_down, star_rating, memory_irrelevant, memory_helpful, memory_recall_positive, wrong_agent, flag_issue, entity_correction
    value: Optional[float] = None  # for star_rating (1-5)
```

- [ ] **Step 2: Create RL policy state schemas**

```python
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel


class RLPolicyStateInDB(BaseModel):
    id: uuid.UUID
    tenant_id: Optional[uuid.UUID] = None
    decision_point: str
    weights: Dict[str, Any]
    version: str
    experience_count: int
    last_updated_at: datetime
    exploration_rate: float

    class Config:
        from_attributes = True


class RLSettingsUpdate(BaseModel):
    exploration_rate: Optional[float] = None
    opt_in_global_learning: Optional[bool] = None
    use_global_baseline: Optional[bool] = None
    min_tenant_experiences: Optional[int] = None
    blend_alpha_growth: Optional[float] = None
    reward_weights: Optional[Dict[str, float]] = None
    review_schedule: Optional[str] = None
    per_decision_overrides: Optional[Dict[str, Any]] = None
```

- [ ] **Step 3: Verify schemas import**

Run: `cd apps/api && python -c "from app.schemas.rl_experience import RLExperienceCreate, RLFeedbackSubmit; from app.schemas.rl_policy_state import RLSettingsUpdate; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/schemas/rl_experience.py apps/api/app/schemas/rl_policy_state.py
git commit -m "feat: add Pydantic schemas for RL experiences and policy states"
```

---

## Chunk 2: Core Services (Experience Store, Reward, Policy Engine)

### Task 6: RL Experience Service

**Files:**
- Create: `apps/api/app/services/rl_experience_service.py`

- [ ] **Step 1: Create the experience service**

This service handles CRUD for experiences, reward assignment, and trajectory-linked backward propagation.

```python
import uuid
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.rl_experience import RLExperience
from app.services import embedding_service


# Decision point constants
DECISION_POINTS = [
    "agent_selection", "memory_recall", "skill_routing",
    "orchestration_routing", "triage_classification",
    "response_generation", "tool_selection", "entity_validation",
    "score_weighting", "sync_strategy", "execution_decision",
    "code_strategy", "deal_stage_advance", "change_significance",
]

# Reward discount factor for backward propagation
TRAJECTORY_DISCOUNT = 0.7


def log_experience(
    db: Session,
    tenant_id: uuid.UUID,
    trajectory_id: uuid.UUID,
    step_index: int,
    decision_point: str,
    state: Dict[str, Any],
    action: Dict[str, Any],
    alternatives: List[Dict[str, Any]] = None,
    explanation: Dict[str, Any] = None,
    policy_version: str = None,
    exploration: bool = False,
    state_text: str = None,
) -> RLExperience:
    """Log a decision as an RL experience. Optionally embeds state text via Gemini."""
    state_embedding = None
    if state_text:
        state_embedding = embedding_service.embed_text(state_text, task_type="RETRIEVAL_DOCUMENT")

    exp = RLExperience(
        tenant_id=tenant_id,
        trajectory_id=trajectory_id,
        step_index=step_index,
        decision_point=decision_point,
        state=state,
        state_embedding=state_embedding,
        action=action,
        alternatives=alternatives or [],
        explanation=explanation,
        policy_version=policy_version,
        exploration=exploration,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def assign_reward(
    db: Session,
    experience_id: uuid.UUID,
    reward: float,
    reward_components: Dict[str, Any],
    reward_source: str,
) -> RLExperience:
    """Assign a reward to a specific experience."""
    exp = db.query(RLExperience).filter(RLExperience.id == experience_id).first()
    if not exp:
        return None
    exp.reward = max(-1.0, min(1.0, reward))
    exp.reward_components = reward_components
    exp.reward_source = reward_source
    exp.rewarded_at = datetime.utcnow()
    db.commit()
    db.refresh(exp)
    return exp


def propagate_reward_backward(
    db: Session,
    trajectory_id: uuid.UUID,
    terminal_reward: float,
    reward_source: str,
) -> int:
    """Propagate reward backward through a trajectory with discount factor."""
    experiences = (
        db.query(RLExperience)
        .filter(RLExperience.trajectory_id == trajectory_id)
        .order_by(RLExperience.step_index.desc())
        .all()
    )
    if not experiences:
        return 0

    updated = 0
    downstream_reward = 0.0
    for i, exp in enumerate(experiences):
        if i == 0:
            # Terminal step gets the full reward
            step_reward = terminal_reward
        else:
            step_reward = downstream_reward * TRAJECTORY_DISCOUNT

        # Combine with any pre-existing direct reward (additive)
        if exp.reward is not None:
            step_reward = max(-1.0, min(1.0, exp.reward + step_reward))

        exp.reward = max(-1.0, min(1.0, step_reward))
        exp.reward_components = {
            "propagated": round(step_reward, 4),
            "source_reward": terminal_reward,
            "direct_reward": exp.reward_components.get("direct", 0) if exp.reward_components else 0,
        }
        exp.reward_source = reward_source
        exp.rewarded_at = datetime.utcnow()
        downstream_reward = step_reward
        updated += 1

    db.commit()
    return updated


def find_similar_experiences(
    db: Session,
    tenant_id: uuid.UUID,
    decision_point: str,
    state_text: str,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Find similar past experiences using pgvector cosine similarity."""
    query_embedding = embedding_service.embed_text(state_text, task_type="RETRIEVAL_QUERY")
    if not query_embedding:
        return []

    # Inline the vector literal via f-string to avoid SQLAlchemy confusing
    # colon-based named params with PostgreSQL type casts (same pattern as embedding_service.py)
    vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"
    sql = text(f"""
        SELECT
            id, trajectory_id, step_index, decision_point,
            state, action, reward, reward_source, explanation,
            exploration, created_at,
            1 - (state_embedding <=> CAST('{vector_literal}' AS vector)) AS similarity
        FROM rl_experiences
        WHERE tenant_id = CAST(:tid AS uuid)
          AND decision_point = :dp
          AND archived_at IS NULL
          AND reward IS NOT NULL
        ORDER BY state_embedding <=> CAST('{vector_literal}' AS vector)
        LIMIT :lim
    """)
    rows = db.execute(sql, {"tid": str(tenant_id), "dp": decision_point, "lim": limit}).fetchall()
    return [
        {
            "id": str(r.id),
            "trajectory_id": str(r.trajectory_id),
            "step_index": r.step_index,
            "state": r.state,
            "action": r.action,
            "reward": r.reward,
            "reward_source": r.reward_source,
            "explanation": r.explanation,
            "exploration": r.exploration,
            "created_at": r.created_at.isoformat(),
            "similarity": float(r.similarity) if r.similarity else 0.0,
        }
        for r in rows
    ]


def get_trajectory(db: Session, trajectory_id: uuid.UUID) -> List[RLExperience]:
    """Get all experiences in a trajectory ordered by step."""
    return (
        db.query(RLExperience)
        .filter(RLExperience.trajectory_id == trajectory_id)
        .order_by(RLExperience.step_index)
        .all()
    )


def get_experiences_paginated(
    db: Session,
    tenant_id: uuid.UUID,
    decision_point: str = None,
    from_date: datetime = None,
    to_date: datetime = None,
    skip: int = 0,
    limit: int = 50,
) -> List[RLExperience]:
    """Paginated experience query for the Learning page."""
    q = db.query(RLExperience).filter(
        RLExperience.tenant_id == tenant_id,
        RLExperience.archived_at.is_(None),
    )
    if decision_point:
        q = q.filter(RLExperience.decision_point == decision_point)
    if from_date:
        q = q.filter(RLExperience.created_at >= from_date)
    if to_date:
        q = q.filter(RLExperience.created_at <= to_date)
    return q.order_by(RLExperience.created_at.desc()).offset(skip).limit(limit).all()


def archive_old_experiences(db: Session, tenant_id: uuid.UUID, days: int = 90) -> int:
    """Archive experiences older than retention window."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    updated = (
        db.query(RLExperience)
        .filter(
            RLExperience.tenant_id == tenant_id,
            RLExperience.created_at < cutoff,
            RLExperience.archived_at.is_(None),
        )
        .update({"archived_at": datetime.utcnow()})
    )
    db.commit()
    return updated
```

- [ ] **Step 2: Verify service imports**

Run: `cd apps/api && python -c "from app.services.rl_experience_service import log_experience, find_similar_experiences, propagate_reward_backward; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/rl_experience_service.py
git commit -m "feat: add RL experience service with pgvector similarity search and backward propagation"
```

---

### Task 7: RL Reward Service

**Files:**
- Create: `apps/api/app/services/rl_reward_service.py`

- [ ] **Step 1: Create the reward service**

This service computes composite rewards from implicit + explicit + admin signals.

```python
import uuid
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.rl_experience import RLExperience
from app.models.tenant_features import TenantFeatures
from app.services import rl_experience_service


# Feedback type to reward mapping
FEEDBACK_REWARDS = {
    "thumbs_up": 0.6,
    "thumbs_down": -0.6,
    "memory_helpful": 0.4,
    "memory_irrelevant": -0.4,
    "memory_partial": 0.1,
    "memory_recall_positive": 0.2,
    "wrong_agent": -0.7,
    "flag_issue": -0.5,
    "entity_correction": -0.3,
}

# Star rating mapping: 1 -> -0.8, 3 -> 0.0, 5 -> +0.8
def star_to_reward(stars: float) -> float:
    return (stars - 3.0) * 0.4


def get_reward_weights(db: Session, tenant_id: uuid.UUID) -> Dict[str, float]:
    """Get tenant-specific reward weights or defaults."""
    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == tenant_id).first()
    if features and features.rl_settings and "reward_weights" in features.rl_settings:
        return features.rl_settings["reward_weights"]
    return {"implicit": 0.3, "explicit": 0.5, "admin": 0.2}


def compute_composite_reward(
    implicit: Optional[float],
    explicit: Optional[float],
    admin: Optional[float],
    weights: Dict[str, float],
) -> float:
    """Compute weighted composite reward, redistributing absent source weights."""
    sources = {}
    if implicit is not None:
        sources["implicit"] = (implicit, weights.get("implicit", 0.3))
    if explicit is not None:
        sources["explicit"] = (explicit, weights.get("explicit", 0.5))
    if admin is not None:
        sources["admin"] = (admin, weights.get("admin", 0.2))

    if not sources:
        return 0.0

    total_weight = sum(w for _, w in sources.values())
    if total_weight == 0:
        return 0.0

    result = sum(val * (w / total_weight) for val, w in sources.values())
    return max(-1.0, min(1.0, result))


def process_explicit_feedback(
    db: Session,
    tenant_id: uuid.UUID,
    trajectory_id: uuid.UUID,
    feedback_type: str,
    step_index: Optional[int] = None,
    value: Optional[float] = None,
) -> int:
    """Process user feedback and assign rewards to the trajectory."""
    if feedback_type == "star_rating" and value is not None:
        reward = star_to_reward(value)
    elif feedback_type in FEEDBACK_REWARDS:
        reward = FEEDBACK_REWARDS[feedback_type]
    else:
        return 0

    weights = get_reward_weights(db, tenant_id)

    if step_index is not None:
        # Target a specific step
        exp = (
            db.query(RLExperience)
            .filter(
                RLExperience.trajectory_id == trajectory_id,
                RLExperience.step_index == step_index,
            )
            .first()
        )
        if exp:
            composite = compute_composite_reward(None, reward, None, weights)
            rl_experience_service.assign_reward(
                db, exp.id, composite,
                {"explicit": reward, "feedback_type": feedback_type},
                "explicit_rating",
            )
            return 1
    else:
        # Propagate backward through entire trajectory
        return rl_experience_service.propagate_reward_backward(
            db, trajectory_id, reward, "explicit_rating"
        )


def process_admin_review(
    db: Session,
    tenant_id: uuid.UUID,
    experience_id: uuid.UUID,
    rating: str,
) -> Optional[RLExperience]:
    """Process admin review rating on a specific experience."""
    rating_rewards = {"good": 0.8, "acceptable": 0.0, "poor": -0.8}
    reward = rating_rewards.get(rating)
    if reward is None:
        return None

    weights = get_reward_weights(db, tenant_id)
    composite = compute_composite_reward(None, None, reward, weights)
    return rl_experience_service.assign_reward(
        db, experience_id, composite,
        {"admin": reward, "rating": rating},
        "admin_review",
    )


def compute_implicit_reward(signals: Dict[str, Any]) -> float:
    """Compute implicit reward from system signals."""
    reward = 0.0
    if signals.get("task_completed"):
        reward += 0.3
    if signals.get("task_failed"):
        reward -= 0.5
    if signals.get("latency_below_p50"):
        reward += 0.1
    if signals.get("user_continued"):
        reward += 0.1
    if signals.get("user_disengaged"):
        reward -= 0.1
    if signals.get("notification_read"):
        reward += 0.1
    if signals.get("notification_dismissed_unread"):
        reward -= 0.2
    if signals.get("entity_referenced"):
        reward += 0.2
    if signals.get("memory_recall_positive_response"):
        reward += 0.2
    if signals.get("deal_advanced"):
        reward += 0.4
    if signals.get("pipeline_succeeded"):
        reward += 0.2
    return max(-1.0, min(1.0, reward))
```

- [ ] **Step 2: Verify service imports**

Run: `cd apps/api && python -c "from app.services.rl_reward_service import process_explicit_feedback, compute_implicit_reward, compute_composite_reward; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/rl_reward_service.py
git commit -m "feat: add RL reward service with composite rewards and backward propagation"
```

---

### Task 8: RL Policy Engine

**Files:**
- Create: `apps/api/app/services/rl_policy_engine.py`

- [ ] **Step 1: Create the policy engine**

This is the core decision-making engine — scores candidates using reward-weighted regression, handles exploration, and generates explanations.

```python
import uuid
import math
import random
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.models.rl_policy_state import RLPolicyState
from app.models.tenant_features import TenantFeatures
from app.services import rl_experience_service


# State text generators per decision point
def _state_text_agent_selection(state: Dict) -> str:
    return f"Task: {state.get('task_type', 'unknown')}, capabilities: {state.get('required_capabilities', [])}, urgency: {state.get('urgency', 'normal')}"


def _state_text_memory_recall(state: Dict) -> str:
    return f"Query: {state.get('query_keywords', '')}, agent: {state.get('agent_name', '')}, context: {state.get('context_summary', '')}"


def _state_text_skill_routing(state: Dict) -> str:
    return f"Task: {state.get('task_type', 'unknown')}, available skills: {state.get('available_skills', [])}"


def _state_text_orchestration_routing(state: Dict) -> str:
    return f"Supervisor: {state.get('supervisor', '')}, sub-agents: {state.get('sub_agents', [])}, complexity: {state.get('task_complexity', 'medium')}"


def _state_text_triage(state: Dict) -> str:
    return f"From: {state.get('sender', '')}, subject: {state.get('subject', '')}, entities: {state.get('entity_mentions', [])}"


def _state_text_default(state: Dict) -> str:
    return f"Decision context: {str(state)[:500]}"


def _state_text_response_generation(state: Dict) -> str:
    return f"Agent: {state.get('agent_name', '')}, message_count: {state.get('message_count', 0)}, topic: {state.get('topic', '')}"


def _state_text_tool_selection(state: Dict) -> str:
    return f"Task: {state.get('task_type', '')}, available_tools: {state.get('available_tools', [])}, context: {state.get('context', '')}"


def _state_text_entity_validation(state: Dict) -> str:
    return f"Entity: {state.get('entity_type', '')} '{state.get('entity_name', '')}', source: {state.get('source', '')}"


def _state_text_score_weighting(state: Dict) -> str:
    return f"Lead: {state.get('lead_name', '')}, rubric: {state.get('rubric_name', '')}, signals: {state.get('signal_count', 0)}"


def _state_text_sync_strategy(state: Dict) -> str:
    return f"Dataset: {state.get('dataset_name', '')}, rows: {state.get('row_count', 0)}, destination: {state.get('destination', '')}"


def _state_text_execution_decision(state: Dict) -> str:
    return f"Workflow: {state.get('workflow_type', '')}, priority: {state.get('priority', 'normal')}, retries: {state.get('retry_count', 0)}"


def _state_text_code_strategy(state: Dict) -> str:
    return f"Task: {state.get('task_description', '')[:200]}, repo: {state.get('repo', '')}, branch: {state.get('branch', '')}"


def _state_text_deal_stage_advance(state: Dict) -> str:
    return f"Deal: {state.get('deal_name', '')}, current_stage: {state.get('current_stage', '')}, score: {state.get('score', 0)}"


def _state_text_change_significance(state: Dict) -> str:
    return f"Competitor: {state.get('competitor_name', '')}, change_type: {state.get('change_type', '')}, source: {state.get('source', '')}"


STATE_TEXT_GENERATORS = {
    "agent_selection": _state_text_agent_selection,
    "memory_recall": _state_text_memory_recall,
    "skill_routing": _state_text_skill_routing,
    "orchestration_routing": _state_text_orchestration_routing,
    "triage_classification": _state_text_triage,
    "response_generation": _state_text_response_generation,
    "tool_selection": _state_text_tool_selection,
    "entity_validation": _state_text_entity_validation,
    "score_weighting": _state_text_score_weighting,
    "sync_strategy": _state_text_sync_strategy,
    "execution_decision": _state_text_execution_decision,
    "code_strategy": _state_text_code_strategy,
    "deal_stage_advance": _state_text_deal_stage_advance,
    "change_significance": _state_text_change_significance,
}


def generate_state_text(decision_point: str, state: Dict) -> str:
    gen = STATE_TEXT_GENERATORS.get(decision_point, _state_text_default)
    return gen(state)


def get_policy(db: Session, tenant_id: uuid.UUID, decision_point: str) -> Optional[RLPolicyState]:
    """Get tenant-specific policy with federated blending against global baseline.

    Phase 1: Binary fallback (tenant or global).
    Phase 2+: Alpha-blended scoring where alpha grows with tenant experience count.
    """
    tenant_policy = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id == tenant_id, RLPolicyState.decision_point == decision_point)
        .first()
    )
    global_policy = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id.is_(None), RLPolicyState.decision_point == decision_point)
        .first()
    )

    if tenant_policy and global_policy:
        # Check if tenant opted into global baseline
        features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == tenant_id).first()
        use_global = features.rl_settings.get("use_global_baseline", True) if features and features.rl_settings else True
        if use_global:
            # Alpha grows with experience count: alpha = min(1.0, count * blend_alpha_growth)
            growth = features.rl_settings.get("blend_alpha_growth", 0.01) if features and features.rl_settings else 0.01
            alpha = min(1.0, tenant_policy.experience_count * growth)
            # Store blending info for explanation generation
            tenant_policy._blend_alpha = alpha
            tenant_policy._global_weights = global_policy.weights
        return tenant_policy

    return tenant_policy or global_policy


def get_exploration_rate(db: Session, tenant_id: uuid.UUID, decision_point: str) -> float:
    """Get exploration rate for a tenant+decision point."""
    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == tenant_id).first()
    if features and features.rl_settings:
        overrides = features.rl_settings.get("per_decision_overrides", {})
        if decision_point in overrides and "exploration_rate" in overrides[decision_point]:
            return overrides[decision_point]["exploration_rate"]
        return features.rl_settings.get("exploration_rate", 0.1)
    return 0.1


def score_candidates(
    db: Session,
    tenant_id: uuid.UUID,
    decision_point: str,
    state: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    state_text: str = None,
) -> List[Dict[str, Any]]:
    """Score candidates using reward-weighted regression over similar experiences."""
    if not state_text:
        state_text = generate_state_text(decision_point, state)

    similar = rl_experience_service.find_similar_experiences(
        db, tenant_id, decision_point, state_text, limit=200
    )

    if not similar:
        # Cold start: return candidates with default scores
        for c in candidates:
            c["rl_score"] = 0.5
            c["experience_count"] = 0
        return candidates

    # Score each candidate by matching against similar experiences
    now = datetime.utcnow()
    lambda_decay = 0.05  # ~14 day half-life

    for candidate in candidates:
        candidate_id = str(candidate.get("id", candidate.get("name", "")))
        weighted_sum = 0.0
        weight_total = 0.0
        match_count = 0

        for exp in similar:
            # Check if this experience chose the same candidate
            exp_action_id = str(exp["action"].get("id", exp["action"].get("name", "")))
            if exp_action_id != candidate_id:
                continue

            days_old = (now - datetime.fromisoformat(exp["created_at"])).days
            recency = math.exp(-lambda_decay * days_old)
            sim = exp.get("similarity", 0.5)
            w = recency * sim
            weighted_sum += exp["reward"] * w
            weight_total += w
            match_count += 1

        candidate["rl_score"] = weighted_sum / weight_total if weight_total > 0 else 0.5
        candidate["experience_count"] = match_count

    return candidates


def select_action(
    db: Session,
    tenant_id: uuid.UUID,
    decision_point: str,
    state: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Select an action using explore/exploit, returns (chosen_action, explanation)."""
    state_text = generate_state_text(decision_point, state)
    scored = score_candidates(db, tenant_id, decision_point, state, candidates, state_text)

    exploration_rate = get_exploration_rate(db, tenant_id, decision_point)
    is_exploration = random.random() < exploration_rate

    if is_exploration:
        # Explore: sample by uncertainty (less-tried candidates more likely)
        safe_candidates = [c for c in scored if c.get("rl_score", 0.5) > -0.5 or c.get("experience_count", 0) == 0]
        if not safe_candidates:
            safe_candidates = scored

        weights = [1.0 / max(c.get("experience_count", 0), 1) for c in safe_candidates]
        total = sum(weights)
        weights = [w / total for w in weights]
        chosen = random.choices(safe_candidates, weights=weights, k=1)[0]
    else:
        # Exploit: pick highest score
        chosen = max(scored, key=lambda c: c.get("rl_score", 0.5))

    alternatives = [
        {"id": str(c.get("id", c.get("name", ""))), "score": round(c.get("rl_score", 0.5), 3)}
        for c in scored if c != chosen
    ]

    explanation = {
        "decision": decision_point,
        "chosen": str(chosen.get("id", chosen.get("name", ""))),
        "score": round(chosen.get("rl_score", 0.5), 3),
        "reason": f"{'Exploration' if is_exploration else 'Highest reward-weighted score'} for {decision_point}",
        "experience_count": chosen.get("experience_count", 0),
        "alternatives": alternatives[:5],
        "exploration": is_exploration,
    }

    return chosen, explanation
```

- [ ] **Step 2: Verify engine imports**

Run: `cd apps/api && python -c "from app.services.rl_policy_engine import select_action, score_candidates, generate_state_text; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/rl_policy_engine.py
git commit -m "feat: add RL policy engine with reward-weighted regression, exploration gate, and explanation generation"
```

---

## Chunk 3: API Routes + Integration with Existing Services

### Task 9: RL API Routes

**Files:**
- Create: `apps/api/app/api/v1/rl.py`
- Modify: `apps/api/app/api/v1/routes.py` (mount new router)

- [ ] **Step 1: Create the RL routes file**

```python
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api import deps
from app.models.rl_experience import RLExperience
from app.models.rl_policy_state import RLPolicyState
from app.models.tenant_features import TenantFeatures
from app.schemas.rl_experience import RLExperienceInDB, RLFeedbackSubmit
from app.schemas.rl_policy_state import RLPolicyStateInDB, RLSettingsUpdate
from app.services import rl_experience_service, rl_reward_service

router = APIRouter()


@router.get("/overview")
def get_overview(
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Aggregated metrics for Learning Overview tab."""
    tid = current_user.tenant_id
    total = db.query(RLExperience).filter(
        RLExperience.tenant_id == tid, RLExperience.archived_at.is_(None)
    ).count()

    rewarded = db.query(RLExperience).filter(
        RLExperience.tenant_id == tid,
        RLExperience.reward.isnot(None),
        RLExperience.archived_at.is_(None),
    ).all()

    avg_reward = sum(e.reward for e in rewarded) / len(rewarded) if rewarded else 0.0

    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == tid).first()
    exploration_rate = features.rl_settings.get("exploration_rate", 0.1) if features and features.rl_settings else 0.1

    latest_policy = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id == tid)
        .order_by(RLPolicyState.last_updated_at.desc())
        .first()
    )

    return {
        "total_experiences": total,
        "avg_reward": round(avg_reward, 3),
        "exploration_rate": exploration_rate,
        "policy_version": latest_policy.version if latest_policy else "v0",
    }


@router.get("/experiences")
def list_experiences(
    decision_point: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Paginated experience list."""
    skip = (page - 1) * per_page
    experiences = rl_experience_service.get_experiences_paginated(
        db, current_user.tenant_id, decision_point, from_date, to_date, skip, per_page
    )
    return [RLExperienceInDB.model_validate(e) for e in experiences]


@router.get("/experiences/{trajectory_id}")
def get_trajectory(
    trajectory_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """All experiences in a trajectory."""
    experiences = rl_experience_service.get_trajectory(db, trajectory_id)
    return [RLExperienceInDB.model_validate(e) for e in experiences if e.tenant_id == current_user.tenant_id]


@router.post("/feedback")
def submit_feedback(
    feedback: RLFeedbackSubmit,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Submit explicit feedback (thumbs up/down, flags, ratings)."""
    updated = rl_reward_service.process_explicit_feedback(
        db, current_user.tenant_id,
        feedback.trajectory_id, feedback.feedback_type,
        feedback.step_index, feedback.value,
    )
    return {"updated_experiences": updated}


@router.get("/decision-points")
def list_decision_points(
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """List all decision points with current scores and experience counts."""
    tid = current_user.tenant_id
    policies = db.query(RLPolicyState).filter(RLPolicyState.tenant_id == tid).all()
    return [RLPolicyStateInDB.model_validate(p) for p in policies]


@router.get("/decision-points/{name}")
def get_decision_point(
    name: str,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Detail for one decision point."""
    policy = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id == current_user.tenant_id, RLPolicyState.decision_point == name)
        .first()
    )
    recent_exp = rl_experience_service.get_experiences_paginated(
        db, current_user.tenant_id, name, limit=20
    )
    return {
        "policy": RLPolicyStateInDB.model_validate(policy) if policy else None,
        "recent_experiences": [RLExperienceInDB.model_validate(e) for e in recent_exp],
    }


@router.get("/reviews/pending")
def get_pending_reviews(
    decision_point: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Admin review queue sorted by uncertainty (unrewarded experiences)."""
    skip = (page - 1) * per_page
    q = db.query(RLExperience).filter(
        RLExperience.tenant_id == current_user.tenant_id,
        RLExperience.reward.is_(None),
        RLExperience.archived_at.is_(None),
    )
    if decision_point:
        q = q.filter(RLExperience.decision_point == decision_point)
    experiences = q.order_by(RLExperience.created_at.desc()).offset(skip).limit(per_page).all()
    return [RLExperienceInDB.model_validate(e) for e in experiences]


@router.post("/reviews/{experience_id}/rate")
def rate_experience(
    experience_id: uuid.UUID,
    rating: str = Query(..., pattern="^(good|acceptable|poor)$"),
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Admin rates an experience."""
    result = rl_reward_service.process_admin_review(
        db, current_user.tenant_id, experience_id, rating
    )
    if not result:
        return {"error": "Experience not found or invalid rating"}
    return RLExperienceInDB.model_validate(result)


@router.get("/settings")
def get_settings(
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Get tenant RL settings."""
    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == current_user.tenant_id).first()
    return {
        "rl_enabled": features.rl_enabled if features else False,
        "settings": features.rl_settings if features and features.rl_settings else {},
    }


@router.put("/settings")
def update_settings(
    settings: RLSettingsUpdate,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Update tenant RL settings."""
    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == current_user.tenant_id).first()
    if not features:
        return {"error": "Tenant features not found"}

    current = features.rl_settings or {}
    updates = settings.model_dump(exclude_none=True)
    current.update(updates)
    features.rl_settings = current
    db.commit()
    return {"rl_enabled": features.rl_enabled, "settings": features.rl_settings}


@router.get("/policy/versions")
def get_policy_versions(
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Policy version history."""
    policies = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id == current_user.tenant_id)
        .order_by(RLPolicyState.last_updated_at.desc())
        .all()
    )
    return [RLPolicyStateInDB.model_validate(p) for p in policies]


@router.post("/policy/rollback")
def rollback_policy(
    decision_point: str,
    version: str,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Restore a previous policy version."""
    # For now, reset experience count threshold to trigger recomputation
    policy = (
        db.query(RLPolicyState)
        .filter(RLPolicyState.tenant_id == current_user.tenant_id, RLPolicyState.decision_point == decision_point)
        .first()
    )
    if not policy:
        return {"error": "Policy not found"}
    policy.version = version
    policy.last_updated_at = datetime.utcnow()
    db.commit()
    return RLPolicyStateInDB.model_validate(policy)


@router.get("/experiments")
def list_experiments(
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Active and recent exploration actions with outcomes."""
    explorations = (
        db.query(RLExperience)
        .filter(
            RLExperience.tenant_id == current_user.tenant_id,
            RLExperience.exploration == True,
            RLExperience.archived_at.is_(None),
        )
        .order_by(RLExperience.created_at.desc())
        .limit(100)
        .all()
    )
    return [RLExperienceInDB.model_validate(e) for e in explorations]


@router.post("/experiments/trigger")
def trigger_experiment(
    decision_point: str,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Manually trigger exploration for a decision point."""
    features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == current_user.tenant_id).first()
    if not features:
        return {"error": "Tenant features not found"}
    current = features.rl_settings or {}
    overrides = current.get("per_decision_overrides", {})
    overrides[decision_point] = {"exploration_rate": 1.0, "triggered_at": datetime.utcnow().isoformat()}
    current["per_decision_overrides"] = overrides
    features.rl_settings = current
    db.commit()
    return {"decision_point": decision_point, "exploration_rate": 1.0, "status": "triggered"}


@router.post("/reviews/batch-rate")
def batch_rate_experiences(
    ratings: list,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Batch rate multiple experiences. Body: [{experience_id, rating}]."""
    results = []
    for item in ratings:
        result = rl_reward_service.process_admin_review(
            db, current_user.tenant_id, uuid.UUID(item["experience_id"]), item["rating"]
        )
        results.append({"experience_id": item["experience_id"], "success": result is not None})
    return {"rated": len([r for r in results if r["success"]]), "results": results}


@router.get("/export")
def export_experiences(
    decision_point: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user=Depends(deps.get_current_active_user),
):
    """Export experience data as CSV."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    q = db.query(RLExperience).filter(
        RLExperience.tenant_id == current_user.tenant_id,
        RLExperience.archived_at.is_(None),
    )
    if decision_point:
        q = q.filter(RLExperience.decision_point == decision_point)
    experiences = q.order_by(RLExperience.created_at.desc()).limit(10000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "trajectory_id", "step_index", "decision_point", "reward", "reward_source", "exploration", "created_at"])
    for e in experiences:
        writer.writerow([str(e.id), str(e.trajectory_id), e.step_index, e.decision_point, e.reward, e.reward_source, e.exploration, e.created_at.isoformat()])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=rl_experiences.csv"})
```

- [ ] **Step 2: Mount the router in routes.py**

Add import at top of `apps/api/app/api/v1/routes.py`:
```python
from app.api.v1 import rl
```

Add mount line after existing routers:
```python
router.include_router(rl.router, prefix="/rl", tags=["reinforcement-learning"])
```

- [ ] **Step 3: Verify routes load**

Run: `cd apps/api && python -c "from app.api.v1.routes import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/api/v1/rl.py apps/api/app/api/v1/routes.py
git commit -m "feat: add RL API routes (16 endpoints) and mount in router"
```

---

### Task 10: Integrate Policy Engine into Task Dispatcher

**Files:**
- Modify: `apps/api/app/services/orchestration/task_dispatcher.py:62` (replace capability scoring)

- [ ] **Step 1: Add RL-aware agent scoring to task_dispatcher.py**

Add import at top:
```python
from app.models.tenant_features import TenantFeatures
from app.services import rl_policy_engine
```

In `find_best_agent()`, wrap the existing scoring loop (around line 58-66) to check RL first. The existing `_calculate_capability_score` remains as the heuristic fallback (Layer 0):

```python
    def find_best_agent(self, db: Session, tenant_id, task_type: str, required_capabilities: list = None):
        """Find the best agent for a task, using RL scoring when enabled."""
        agents = db.query(Agent).filter(
            Agent.tenant_id == tenant_id,
            Agent.status == "active"
        ).all()

        if not agents:
            return None

        # Check if RL is enabled for this tenant
        features = db.query(TenantFeatures).filter(TenantFeatures.tenant_id == tenant_id).first()
        rl_enabled = features.rl_enabled if features else False

        if rl_enabled:
            candidates = [
                {"id": str(a.id), "name": a.name, "capabilities": a.capabilities or []}
                for a in agents
            ]
            state = {
                "task_type": task_type,
                "required_capabilities": required_capabilities or [],
                "agent_count": len(agents),
            }
            try:
                chosen, explanation = rl_policy_engine.select_action(
                    db, tenant_id, "agent_selection", state, candidates
                )
                # Find the agent object matching the chosen action
                for agent in agents:
                    if str(agent.id) == chosen.get("id"):
                        return agent
            except Exception:
                pass  # Fall through to heuristic scoring

        # Heuristic fallback (Layer 0)
        best_agent = None
        best_score = -1
        for agent in agents:
            score = self._calculate_capability_score(agent, required_capabilities)
            if score > best_score:
                best_score = score
                best_agent = agent
        return best_agent
```

- [ ] **Step 2: Verify dispatcher still works**

Run: `cd apps/api && python -c "from app.services.orchestration.task_dispatcher import TaskDispatcher; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/services/orchestration/task_dispatcher.py
git commit -m "feat: integrate RL policy engine into task dispatcher for agent selection"
```

---

### Task 11: Integrate RL into evaluate_task Activity

**Files:**
- Modify: `apps/api/app/workflows/activities/task_execution.py:303-322` (add experience logging alongside existing +0.02)

- [ ] **Step 1: Add RL experience logging to evaluate_task**

Add import at top of file:
```python
from app.services import rl_experience_service
```

After the existing skill proficiency update block (lines 303-322), add experience logging:
```python
# Log RL experience (Phase 1: dual-write — both old +0.02 and RL experience)
try:
    rl_experience_service.log_experience(
        db=db,
        tenant_id=task.tenant_id,
        trajectory_id=task.id,  # use task ID as trajectory
        step_index=0,
        decision_point="skill_routing",
        state={"task_type": task.task_type, "agent_id": str(task.agent_id)},
        action={"skill_name": task.task_type},
        state_text=f"Task: {task.task_type}, agent: {task.agent_id}",
    )
except Exception:
    pass  # RL logging should never break task execution
```

- [ ] **Step 2: Verify activity still loads**

Run: `cd apps/api && python -c "from app.workflows.activities.task_execution import evaluate_task; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/workflows/activities/task_execution.py
git commit -m "feat: add RL experience logging to evaluate_task activity (Phase 1 dual-write)"
```

---

### Task 12: RL Policy Update Workflow (Temporal)

**Files:**
- Create: `apps/api/app/workflows/activities/rl_policy_update.py`
- Modify: `apps/api/app/workers/orchestration_worker.py` (register new workflow + activities)

- [ ] **Step 1: Create RL policy update activities**

```python
import uuid
from datetime import datetime
from temporalio import activity
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db_session
from app.models.rl_experience import RLExperience
from app.models.rl_policy_state import RLPolicyState
from app.models.tenant_features import TenantFeatures
from app.services import rl_experience_service


@activity.defn
async def collect_tenant_experiences(tenant_id: str) -> dict:
    """Collect experience statistics for a tenant."""
    with get_db_session() as db:
        tid = uuid.UUID(tenant_id)
        stats = (
            db.query(
                RLExperience.decision_point,
                func.count(RLExperience.id).label("count"),
                func.avg(RLExperience.reward).label("avg_reward"),
            )
            .filter(
                RLExperience.tenant_id == tid,
                RLExperience.archived_at.is_(None),
                RLExperience.reward.isnot(None),
            )
            .group_by(RLExperience.decision_point)
            .all()
        )
        return {
            "tenant_id": tenant_id,
            "decision_points": {
                s.decision_point: {"count": s.count, "avg_reward": float(s.avg_reward or 0)}
                for s in stats
            },
        }


@activity.defn
async def update_tenant_policy(tenant_id: str, decision_point: str) -> dict:
    """Recompute policy weights for a tenant+decision_point from all rewarded experiences."""
    with get_db_session() as db:
        tid = uuid.UUID(tenant_id)
        experiences = (
            db.query(RLExperience)
            .filter(
                RLExperience.tenant_id == tid,
                RLExperience.decision_point == decision_point,
                RLExperience.reward.isnot(None),
                RLExperience.archived_at.is_(None),
            )
            .all()
        )

        if not experiences:
            return {"tenant_id": tenant_id, "decision_point": decision_point, "updated": False}

        # Compute action-level aggregate scores
        action_scores = {}
        for exp in experiences:
            action_key = str(exp.action.get("id", exp.action.get("name", "unknown")))
            if action_key not in action_scores:
                action_scores[action_key] = {"total_reward": 0, "count": 0}
            action_scores[action_key]["total_reward"] += exp.reward
            action_scores[action_key]["count"] += 1

        weights = {
            k: {"avg_reward": v["total_reward"] / v["count"], "count": v["count"]}
            for k, v in action_scores.items()
        }

        policy = (
            db.query(RLPolicyState)
            .filter(RLPolicyState.tenant_id == tid, RLPolicyState.decision_point == decision_point)
            .first()
        )

        if policy:
            old_version = int(policy.version.replace("v", "")) if policy.version.startswith("v") else 0
            policy.weights = weights
            policy.version = f"v{old_version + 1}"
            policy.experience_count = len(experiences)
            policy.last_updated_at = datetime.utcnow()
        else:
            policy = RLPolicyState(
                tenant_id=tid,
                decision_point=decision_point,
                weights=weights,
                version="v1",
                experience_count=len(experiences),
            )
            db.add(policy)

        db.commit()
        return {"tenant_id": tenant_id, "decision_point": decision_point, "updated": True, "version": policy.version}


@activity.defn
async def anonymize_and_aggregate_global(decision_point: str) -> dict:
    """Aggregate anonymized experience data from opt-in tenants into global baseline."""
    with get_db_session() as db:
        # Get tenants that opted into global learning
        opt_in_tenants = (
            db.query(TenantFeatures)
            .filter(TenantFeatures.rl_enabled == True)
            .all()
        )
        opt_in_ids = [
            f.tenant_id for f in opt_in_tenants
            if f.rl_settings and f.rl_settings.get("opt_in_global_learning", True)
        ]

        if not opt_in_ids:
            return {"decision_point": decision_point, "updated": False}

        # Aggregate action scores across opt-in tenants (anonymized — no tenant_id in output)
        experiences = (
            db.query(RLExperience)
            .filter(
                RLExperience.tenant_id.in_(opt_in_ids),
                RLExperience.decision_point == decision_point,
                RLExperience.reward.isnot(None),
                RLExperience.archived_at.is_(None),
            )
            .all()
        )

        action_scores = {}
        for exp in experiences:
            action_key = str(exp.action.get("id", exp.action.get("name", "unknown")))
            if action_key not in action_scores:
                action_scores[action_key] = {"total_reward": 0, "count": 0}
            action_scores[action_key]["total_reward"] += exp.reward
            action_scores[action_key]["count"] += 1

        weights = {
            k: {"avg_reward": v["total_reward"] / v["count"], "count": v["count"]}
            for k, v in action_scores.items()
        }

        # Upsert global baseline (tenant_id IS NULL)
        global_policy = (
            db.query(RLPolicyState)
            .filter(RLPolicyState.tenant_id.is_(None), RLPolicyState.decision_point == decision_point)
            .first()
        )
        if global_policy:
            old_ver = int(global_policy.version.replace("v", "")) if global_policy.version.startswith("v") else 0
            global_policy.weights = weights
            global_policy.version = f"v{old_ver + 1}"
            global_policy.experience_count = len(experiences)
            global_policy.last_updated_at = datetime.utcnow()
        else:
            global_policy = RLPolicyState(
                tenant_id=None,
                decision_point=decision_point,
                weights=weights,
                version="v1",
                experience_count=len(experiences),
            )
            db.add(global_policy)

        db.commit()
        return {"decision_point": decision_point, "updated": True, "tenants": len(opt_in_ids)}


@activity.defn
async def archive_old_experiences(tenant_id: str, retention_days: int = 90) -> dict:
    """Archive experiences beyond retention window."""
    with get_db_session() as db:
        count = rl_experience_service.archive_old_experiences(db, uuid.UUID(tenant_id), retention_days)
        return {"tenant_id": tenant_id, "archived": count}
```

- [ ] **Step 2: Create the RLPolicyUpdateWorkflow class**

Create `apps/api/app/workflows/rl_policy_update_workflow.py`:

```python
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.rl_policy_update import (
        collect_tenant_experiences,
        update_tenant_policy,
        anonymize_and_aggregate_global,
        archive_old_experiences,
    )
    from app.services.rl_experience_service import DECISION_POINTS


@workflow.defn
class RLPolicyUpdateWorkflow:
    """Nightly batch workflow: collect -> update per-tenant -> anonymize for global -> archive."""

    @workflow.run
    async def run(self, tenant_id: str) -> dict:
        # Step 1: Collect experience stats
        stats = await workflow.execute_activity(
            collect_tenant_experiences, args=[tenant_id],
            start_to_close_timeout=timedelta(minutes=5),
        )

        # Step 2: Update tenant policy for each decision point with data
        updated = []
        for dp, dp_stats in stats.get("decision_points", {}).items():
            if dp_stats.get("count", 0) > 0:
                result = await workflow.execute_activity(
                    update_tenant_policy, args=[tenant_id, dp],
                    start_to_close_timeout=timedelta(minutes=5),
                )
                updated.append(result)

        # Step 3: Anonymize and aggregate into global baseline
        for dp in DECISION_POINTS:
            await workflow.execute_activity(
                anonymize_and_aggregate_global, args=[dp],
                start_to_close_timeout=timedelta(minutes=10),
            )

        # Step 4: Archive old experiences
        archive_result = await workflow.execute_activity(
            archive_old_experiences, args=[tenant_id, 90],
            start_to_close_timeout=timedelta(minutes=5),
        )

        return {
            "tenant_id": tenant_id,
            "policies_updated": len(updated),
            "archived": archive_result.get("archived", 0),
        }
```

- [ ] **Step 3: Register in orchestration_worker.py**

Add imports at top:
```python
from app.workflows.activities.rl_policy_update import (
    collect_tenant_experiences,
    update_tenant_policy,
    anonymize_and_aggregate_global,
    archive_old_experiences,
)
from app.workflows.rl_policy_update_workflow import RLPolicyUpdateWorkflow
```

Add workflow to the `workflows=[]` list (around lines 107-118):
```python
RLPolicyUpdateWorkflow,
```

Add activities to the `activities=[]` list (around lines 119-161):
```python
collect_tenant_experiences,
update_tenant_policy,
anonymize_and_aggregate_global,
archive_old_experiences,
```

- [ ] **Step 4: Verify worker loads**

Run: `cd apps/api && python -c "from app.workers.orchestration_worker import run_orchestration_worker; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/workflows/activities/rl_policy_update.py apps/api/app/workflows/rl_policy_update_workflow.py apps/api/app/workers/orchestration_worker.py
git commit -m "feat: add RLPolicyUpdateWorkflow + activities (collect, update, anonymize, archive)"
```

---

## Chunk 4: Frontend — Learning Page + Chat Feedback

### Task 13: Learning Page API Service

**Files:**
- Create: `apps/web/src/services/learningService.js`

- [ ] **Step 1: Create the API client**

```javascript
import api from './api';

const learningService = {
  getOverview: async () => { const r = await api.get('/rl/overview'); return r.data; },
  getExperiences: async (params = {}) => { const r = await api.get('/rl/experiences', { params }); return r.data; },
  getTrajectory: async (trajectoryId) => { const r = await api.get(`/rl/experiences/${trajectoryId}`); return r.data; },
  submitFeedback: async (data) => { const r = await api.post('/rl/feedback', data); return r.data; },
  getDecisionPoints: async () => { const r = await api.get('/rl/decision-points'); return r.data; },
  getDecisionPoint: async (name) => { const r = await api.get(`/rl/decision-points/${name}`); return r.data; },
  getExperiments: async () => { const r = await api.get('/rl/experiments'); return r.data; },
  triggerExperiment: async (decisionPoint) => { const r = await api.post(`/rl/experiments/trigger?decision_point=${decisionPoint}`); return r.data; },
  getPendingReviews: async (params = {}) => { const r = await api.get('/rl/reviews/pending', { params }); return r.data; },
  rateExperience: async (experienceId, rating) => { const r = await api.post(`/rl/reviews/${experienceId}/rate?rating=${rating}`); return r.data; },
  batchRate: async (ratings) => { const r = await api.post('/rl/reviews/batch-rate', ratings); return r.data; },
  getSettings: async () => { const r = await api.get('/rl/settings'); return r.data; },
  updateSettings: async (data) => { const r = await api.put('/rl/settings', data); return r.data; },
  getPolicyVersions: async () => { const r = await api.get('/rl/policy/versions'); return r.data; },
  rollbackPolicy: async (decisionPoint, version) => { const r = await api.post(`/rl/policy/rollback?decision_point=${decisionPoint}&version=${version}`); return r.data; },
  exportExperiences: async (decisionPoint) => { const r = await api.get('/rl/export', { params: { decision_point: decisionPoint }, responseType: 'blob' }); return r.data; },
};

export default learningService;
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/services/learningService.js
git commit -m "feat: add learning service API client"
```

---

### Task 14: Learning Page Component

**Files:**
- Create: `apps/web/src/pages/LearningPage.js`

- [ ] **Step 1: Create the Learning page with 5 tabs**

Create a tabbed page with Overview, Decision Points, Experiments, Reviews, and Settings tabs. Use Bootstrap Nav tabs, glassmorphic metric tiles, and the existing Ocean Theme patterns from DashboardPage.

The Overview tab shows 4 metric tiles (Total Experiences, Avg Reward, Exploration Rate, Policy Version) and loads data from `learningService.getOverview()`.

Decision Points tab lists all decision points with scores from `learningService.getDecisionPoints()`.

Reviews tab shows pending reviews from `learningService.getPendingReviews()` with Good/Acceptable/Poor rating buttons.

Settings tab shows exploration rate slider, global baseline toggle, reward weight inputs, and saves via `learningService.updateSettings()`.

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/pages/LearningPage.js
git commit -m "feat: add Learning page with overview, decision points, reviews, and settings tabs"
```

---

### Task 15: Chat Feedback Actions Component

**Files:**
- Create: `apps/web/src/components/chat/FeedbackActions.js`
- Modify: `apps/web/src/pages/ChatPage.js` (integrate FeedbackActions on agent messages)

- [ ] **Step 1: Create inline feedback component**

A small component that renders after each agent message in chat. Shows thumbs up/down buttons and a "Flag Issue" dropdown. Calls `learningService.submitFeedback()` on click.

Props: `trajectoryId`, `stepIndex` (optional).

UI: Two small icon buttons (thumbs up, thumbs down) + a dropdown for "Wrong Agent", "Irrelevant Memory", "Incorrect Info", "Too Slow".

- [ ] **Step 2: Integrate FeedbackActions into ChatPage.js**

Import the component in `apps/web/src/pages/ChatPage.js`:
```javascript
import FeedbackActions from '../components/chat/FeedbackActions';
```

In the message rendering loop, add `<FeedbackActions />` after each agent/assistant message bubble. Pass `trajectoryId={message.trajectory_id}` and `stepIndex={message.step_index}` if available from the message object. Only show on messages where `message.role === 'assistant'`.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/chat/FeedbackActions.js apps/web/src/pages/ChatPage.js
git commit -m "feat: add chat FeedbackActions component and integrate into ChatPage"
```

---

### Task 16: Register Routes and Navigation

**Files:**
- Modify: `apps/web/src/App.js` (add route)
- Modify: `apps/web/src/components/Layout.js` (add sidebar entry)

- [ ] **Step 1: Add route in App.js**

Add import at top:
```javascript
import LearningPage from './pages/LearningPage';
```

Add route after existing AI Operations routes (around line 88):
```jsx
<Route path="/learning" element={<ProtectedRoute><LearningPage /></ProtectedRoute>} />
```

- [ ] **Step 2: Add sidebar entry in Layout.js**

In the AI Operations section (Section 1, around line 58-66), add after the Skills entry (line 65):
```javascript
{ path: '/learning', icon: ChartLine, label: t('sidebar.learning'), description: t('sidebar_desc.learning') },
```

Add `FaChartLine as ChartLine` to the `react-icons/fa` import at top (line 4-18):
```javascript
import {
  ...existing imports...,
  FaChartLine as ChartLine
} from 'react-icons/fa';
```

- [ ] **Step 3: Verify app compiles**

Run: `cd apps/web && npm start` (check for compilation errors)
Expected: No compilation errors. Learning page accessible at `/learning`.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/App.js apps/web/src/components/Layout.js
git commit -m "feat: register Learning page route and sidebar navigation entry"
```

---

### Task 17: i18n Translation Files

**Files:**
- Create: `apps/web/src/i18n/locales/en/learning.json`
- Create: `apps/web/src/i18n/locales/es/learning.json`
- Modify: `apps/web/src/i18n/i18n.js` (register namespace)

- [ ] **Step 1: Create English translations**

```json
{
  "title": "Learning",
  "overview": {
    "title": "Overview",
    "totalExperiences": "Total Experiences",
    "avgReward": "Avg Reward (30d)",
    "explorationRate": "Exploration Rate",
    "policyVersion": "Policy Version"
  },
  "decisionPoints": {
    "title": "Decision Points",
    "name": "Decision Point",
    "score": "Score",
    "experiences": "Experiences",
    "explorationRatio": "Exploration %"
  },
  "experiments": {
    "title": "Experiments"
  },
  "reviews": {
    "title": "Reviews",
    "pending": "Pending Reviews",
    "good": "Good",
    "acceptable": "Acceptable",
    "poor": "Poor"
  },
  "settings": {
    "title": "Settings",
    "explorationRate": "Exploration Rate",
    "globalBaseline": "Use Global Baseline",
    "optInGlobal": "Contribute to Global Learning",
    "rewardWeights": "Reward Weights",
    "implicit": "Implicit",
    "explicit": "Explicit",
    "admin": "Admin",
    "save": "Save Settings"
  },
  "feedback": {
    "thumbsUp": "Helpful",
    "thumbsDown": "Not helpful",
    "wrongAgent": "Wrong agent",
    "irrelevantMemory": "Irrelevant memory",
    "incorrectInfo": "Incorrect info",
    "tooSlow": "Too slow",
    "flagIssue": "Flag issue"
  }
}
```

- [ ] **Step 2: Create Spanish translations**

```json
{
  "title": "Aprendizaje",
  "overview": {
    "title": "Resumen",
    "totalExperiences": "Experiencias Totales",
    "avgReward": "Recompensa Prom. (30d)",
    "explorationRate": "Tasa de Exploración",
    "policyVersion": "Versión de Política"
  },
  "decisionPoints": {
    "title": "Puntos de Decisión",
    "name": "Punto de Decisión",
    "score": "Puntuación",
    "experiences": "Experiencias",
    "explorationRatio": "% Exploración"
  },
  "experiments": {
    "title": "Experimentos"
  },
  "reviews": {
    "title": "Revisiones",
    "pending": "Revisiones Pendientes",
    "good": "Buena",
    "acceptable": "Aceptable",
    "poor": "Mala"
  },
  "settings": {
    "title": "Configuración",
    "explorationRate": "Tasa de Exploración",
    "globalBaseline": "Usar Línea Base Global",
    "optInGlobal": "Contribuir al Aprendizaje Global",
    "rewardWeights": "Pesos de Recompensa",
    "implicit": "Implícito",
    "explicit": "Explícito",
    "admin": "Administrador",
    "save": "Guardar Configuración"
  },
  "feedback": {
    "thumbsUp": "Útil",
    "thumbsDown": "No útil",
    "wrongAgent": "Agente incorrecto",
    "irrelevantMemory": "Memoria irrelevante",
    "incorrectInfo": "Información incorrecta",
    "tooSlow": "Muy lento",
    "flagIssue": "Reportar problema"
  }
}
```

- [ ] **Step 3: Add sidebar keys to common.json**

Add to `apps/web/src/i18n/locales/en/common.json` inside the `sidebar` object:
```json
"learning": "Learning"
```
And inside the `sidebar_desc` object:
```json
"learning": "RL insights & settings"
```

Add to `apps/web/src/i18n/locales/es/common.json` inside the `sidebar` object:
```json
"learning": "Aprendizaje"
```
And inside the `sidebar_desc` object:
```json
"learning": "Información y ajustes de RL"
```

- [ ] **Step 4: Register namespace in i18n.js**

Add `learning` to the namespace list and resource loading in `apps/web/src/i18n/i18n.js`.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/i18n/locales/en/learning.json apps/web/src/i18n/locales/es/learning.json apps/web/src/i18n/locales/en/common.json apps/web/src/i18n/locales/es/common.json apps/web/src/i18n/i18n.js
git commit -m "feat: add i18n translations for Learning page (en/es) + sidebar keys"
```

---

## Task Dependency Summary

```
Task 1 (Migration)
  └─> Task 2 (RLExperience model)
  └─> Task 3 (RLPolicyState model)
        └─> Task 4 (Register models + modify existing)
              └─> Task 5 (Schemas)
                    └─> Task 6 (Experience service)
                    └─> Task 7 (Reward service)
                          └─> Task 8 (Policy engine)
                                └─> Task 9 (API routes)
                                └─> Task 10 (Integrate dispatcher)
                                └─> Task 11 (Integrate evaluate_task)
                          └─> Task 12 (Temporal workflow)
              └─> Task 13 (Frontend API service)
                    └─> Task 14 (Learning page)
                    └─> Task 15 (Feedback component)
                          └─> Task 16 (Routes + nav)
                                └─> Task 17 (i18n)
```

Tasks 6-8 can run in parallel. Tasks 9-12 can run in parallel after 6-8. Tasks 13-17 can run in parallel with backend tasks after Task 5.
