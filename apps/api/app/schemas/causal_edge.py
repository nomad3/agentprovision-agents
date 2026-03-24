"""Schemas for causal edges."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import uuid

from pydantic import BaseModel, Field


class CauseType(str, Enum):
    TOOL_CALL = "tool_call"
    AGENT_ACTION = "agent_action"
    WORKFLOW_STEP = "workflow_step"
    USER_ACTION = "user_action"
    EXTERNAL_EVENT = "external_event"


class EffectType(str, Enum):
    STATE_CHANGE = "state_change"
    GOAL_PROGRESS = "goal_progress"
    COMMITMENT_FULFILLED = "commitment_fulfilled"
    ENTITY_CREATED = "entity_created"
    NOTIFICATION = "notification"
    EXTERNAL_OUTCOME = "external_outcome"


class CausalStatus(str, Enum):
    HYPOTHESIS = "hypothesis"
    CORROBORATED = "corroborated"
    CONFIRMED = "confirmed"
    DISPROVEN = "disproven"


class CausalEdgeCreate(BaseModel):
    cause_type: CauseType
    cause_ref: Dict[str, Any] = Field(default_factory=dict)
    cause_summary: str
    effect_type: EffectType
    effect_ref: Dict[str, Any] = Field(default_factory=dict)
    effect_summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    mechanism: Optional[str] = None
    source_assertion_id: Optional[uuid.UUID] = None
    agent_slug: Optional[str] = None


class CausalEdgeInDB(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    cause_type: str
    cause_ref: Dict[str, Any] = Field(default_factory=dict)
    cause_summary: str
    effect_type: str
    effect_ref: Dict[str, Any] = Field(default_factory=dict)
    effect_summary: str
    confidence: float
    mechanism: Optional[str] = None
    observation_count: int
    status: str
    source_assertion_id: Optional[uuid.UUID] = None
    agent_slug: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
