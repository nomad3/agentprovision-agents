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
