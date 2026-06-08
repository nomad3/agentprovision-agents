"""Schemas for commitment records."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.accountable_learning import ESCALATION_POLICIES, RISK_THRESHOLDS


def _validate_optional_choice(value, allowed, name):
    if value is not None and value not in allowed:
        raise ValueError(f"{name} {value!r} not in {sorted(allowed)}")
    return value


def strip_blank_refs(value):
    """Drop blank/whitespace string entries from a refs list (None passes through).

    Shared by the proof-gate input schemas so an empty string can never be
    accepted as evidence (adversarial-review HIGH finding)."""
    if value is None:
        return value
    return [s.strip() for s in value if isinstance(s, str) and s.strip()]


class CommitmentType(str, Enum):
    ACTION = "action"
    FOLLOWUP = "followup"
    DELIVERY = "delivery"
    NOTIFICATION = "notification"
    PREDICTION = "prediction"  # Gap 3: Luna makes a verifiable claim/forecast


class CommitmentState(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FULFILLED = "fulfilled"
    BROKEN = "broken"
    CANCELLED = "cancelled"
    # Accountable Learning & Commitment System (plan 2026-06-08 §6).
    # Added to the canonical vocabulary rather than forking new spellings:
    # the plan's "done"->fulfilled, "failed"->broken, "canceled"->cancelled.
    BLOCKED = "blocked"
    AT_RISK = "at_risk"
    RENEGOTIATED = "renegotiated"


class CommitmentSourceType(str, Enum):
    TOOL_CALL = "tool_call"
    WORKFLOW_STEP = "workflow_step"
    MANUAL = "manual"
    CHAT = "chat"  # Auto-extracted from Luna's chat responses (Gap 3)


class CommitmentPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class CommitmentRecordCreate(BaseModel):
    owner_agent_slug: str
    title: str
    description: Optional[str] = None
    commitment_type: CommitmentType = CommitmentType.ACTION
    priority: CommitmentPriority = CommitmentPriority.NORMAL
    source_type: CommitmentSourceType = CommitmentSourceType.TOOL_CALL
    source_ref: Dict[str, Any] = Field(default_factory=dict)
    due_at: Optional[datetime] = None
    goal_id: Optional[uuid.UUID] = None
    related_entity_ids: List[str] = Field(default_factory=list)
    # Accountable Learning fields (plan 2026-06-08 §6).
    contract_id: Optional[uuid.UUID] = None
    proof_required: List[str] = Field(default_factory=list)
    stakeholder_refs: List[str] = Field(default_factory=list)
    risk_threshold: Optional[str] = None
    escalation_policy: Optional[str] = None
    checkpoint_at: Optional[datetime] = None
    escalation_at: Optional[datetime] = None
    stale_after: Optional[datetime] = None

    @field_validator("risk_threshold")
    @classmethod
    def _v_risk(cls, v):
        return _validate_optional_choice(v, RISK_THRESHOLDS, "risk_threshold")

    @field_validator("escalation_policy")
    @classmethod
    def _v_esc(cls, v):
        return _validate_optional_choice(v, ESCALATION_POLICIES, "escalation_policy")


class CommitmentRecordUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    commitment_type: Optional[CommitmentType] = None
    priority: Optional[CommitmentPriority] = None
    state: Optional[CommitmentState] = None
    due_at: Optional[datetime] = None
    goal_id: Optional[uuid.UUID] = None
    related_entity_ids: Optional[List[str]] = None
    broken_reason: Optional[str] = None
    # Accountable Learning fields (plan 2026-06-08 §6).
    proof_required: Optional[List[str]] = None
    proof_refs: Optional[List[str]] = None
    blocker_refs: Optional[List[str]] = None
    stakeholder_refs: Optional[List[str]] = None
    risk_threshold: Optional[str] = None
    escalation_policy: Optional[str] = None
    checkpoint_at: Optional[datetime] = None
    escalation_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    stale_after: Optional[datetime] = None

    @field_validator("risk_threshold")
    @classmethod
    def _v_risk(cls, v):
        return _validate_optional_choice(v, RISK_THRESHOLDS, "risk_threshold")

    @field_validator("escalation_policy")
    @classmethod
    def _v_esc(cls, v):
        return _validate_optional_choice(v, ESCALATION_POLICIES, "escalation_policy")

    @field_validator("proof_refs")
    @classmethod
    def _v_proof_refs(cls, v):
        # Drop blank/whitespace proof entries so they can never count as
        # evidence (adversarial-review HIGH). The service gate strips too;
        # this keeps the persisted list clean on any PATCH path.
        return strip_blank_refs(v)


class CommitmentRecordInDB(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    owner_agent_slug: str
    created_by: Optional[uuid.UUID] = None
    title: str
    description: Optional[str] = None
    commitment_type: str
    state: str
    priority: str
    source_type: str
    source_ref: Dict[str, Any] = Field(default_factory=dict)
    due_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None
    broken_at: Optional[datetime] = None
    broken_reason: Optional[str] = None
    goal_id: Optional[uuid.UUID] = None
    related_entity_ids: List[Any] = Field(default_factory=list)
    # Accountable Learning fields (plan 2026-06-08 §6).
    contract_id: Optional[uuid.UUID] = None
    proof_required: List[Any] = Field(default_factory=list)
    proof_refs: List[Any] = Field(default_factory=list)
    stakeholder_refs: List[Any] = Field(default_factory=list)
    blocker_refs: List[Any] = Field(default_factory=list)
    risk_threshold: Optional[str] = None
    escalation_policy: Optional[str] = None
    checkpoint_at: Optional[datetime] = None
    escalation_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    stale_after: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
