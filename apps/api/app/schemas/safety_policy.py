"""Schemas for governed action taxonomy, policy enforcement, and evidence packs."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    MCP_TOOL = "mcp_tool"
    WORKFLOW_ACTION = "workflow_action"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    INTERNAL_MUTATION = "internal_mutation"
    EXTERNAL_WRITE = "external_write"
    EXECUTION_CONTROL = "execution_control"
    ORCHESTRATION_CONTROL = "orchestration_control"


class SideEffectLevel(str, Enum):
    NONE = "none"
    INTERNAL_STATE = "internal_state"
    EXTERNAL_WRITE = "external_write"
    CODE_EXECUTION = "code_execution"


class Reversibility(str, Enum):
    REVERSIBLE = "reversible"
    PARTIAL = "partial"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_LOGGING = "allow_with_logging"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_REVIEW = "require_review"
    BLOCK = "block"


class AutonomyTier(str, Enum):
    OBSERVE_ONLY = "observe_only"
    RECOMMEND_ONLY = "recommend_only"
    SUPERVISED_EXECUTION = "supervised_execution"
    BOUNDED_AUTONOMOUS_EXECUTION = "bounded_autonomous_execution"


class TenantActionPolicyBase(BaseModel):
    action_type: ActionType
    action_name: str
    channel: str = Field(default="*", description="Specific channel or '*' for all channels")
    decision: PolicyDecision
    rationale: Optional[str] = None
    enabled: bool = True


class TenantActionPolicyUpsert(TenantActionPolicyBase):
    pass


class TenantActionPolicy(TenantActionPolicyBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SafetyActionEvaluationRequest(BaseModel):
    action_type: ActionType
    action_name: str
    channel: str = "web"


class SafetyActionEvaluation(BaseModel):
    action_key: str
    action_type: ActionType
    action_name: str
    category: str
    channel: str
    risk_class: RiskClass
    risk_level: RiskLevel
    side_effect_level: SideEffectLevel
    reversibility: Reversibility
    default_decision: PolicyDecision
    decision: PolicyDecision
    decision_source: str
    rationale: str
    policy_override_id: Optional[uuid.UUID] = None


class SafetyActionCatalogEntry(BaseModel):
    action_key: str
    action_type: ActionType
    action_name: str
    category: str
    risk_class: RiskClass
    risk_level: RiskLevel
    side_effect_level: SideEffectLevel
    reversibility: Reversibility
    default_channel_policies: Dict[str, PolicyDecision]
    effective_decision: PolicyDecision
    decision_source: str
    rationale: str
    policy_override_id: Optional[uuid.UUID] = None


class SafetyEvidencePackBase(BaseModel):
    action_type: ActionType
    action_name: str
    channel: str
    decision: PolicyDecision
    decision_source: str
    risk_class: RiskClass
    risk_level: RiskLevel
    evidence_required: bool
    evidence_sufficient: bool
    world_state_facts: List[Dict[str, Any] | str] = Field(default_factory=list)
    recent_observations: List[Dict[str, Any] | str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)
    proposed_action: Dict[str, Any] = Field(default_factory=dict)
    expected_downside: Optional[str] = None
    context_summary: Optional[str] = None
    context_ref: Dict[str, Any] = Field(default_factory=dict)
    agent_slug: Optional[str] = None


class SafetyEvidencePack(SafetyEvidencePackBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class AgentTrustProfileBase(BaseModel):
    agent_slug: str
    trust_score: float
    confidence: float
    autonomy_tier: AutonomyTier
    reward_signal: float
    provider_signal: float
    rated_experience_count: int
    provider_review_count: int
    rationale: str


class AgentTrustProfile(AgentTrustProfileBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentTrustRecomputeRequest(BaseModel):
    agent_slug: Optional[str] = None


class SafetyEnforcementRequest(BaseModel):
    action_type: ActionType
    action_name: str
    channel: str = "web"
    world_state_facts: List[Dict[str, Any] | str] = Field(default_factory=list)
    recent_observations: List[Dict[str, Any] | str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    uncertainty_notes: List[str] = Field(default_factory=list)
    proposed_action: Dict[str, Any] = Field(default_factory=dict)
    expected_downside: Optional[str] = None
    context_summary: Optional[str] = None
    context_ref: Dict[str, Any] = Field(default_factory=dict)
    agent_slug: Optional[str] = None


class SafetyEnforcementResult(SafetyActionEvaluation):
    evidence_required: bool
    evidence_sufficient: bool
    evidence_pack_id: Optional[uuid.UUID] = None
    agent_trust_score: Optional[float] = None
    autonomy_tier: Optional[AutonomyTier] = None
    trust_confidence: Optional[float] = None
    trust_source: Optional[str] = None
