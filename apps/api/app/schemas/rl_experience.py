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
