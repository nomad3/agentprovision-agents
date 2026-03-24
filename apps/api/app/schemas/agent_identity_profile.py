"""Schemas for agent identity profiles."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


class EscalationThreshold(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    NEVER = "never"


class PlanningStyle(str, Enum):
    STEP_BY_STEP = "step_by_step"
    EXPLORATORY = "exploratory"
    MINIMAL = "minimal"
    THOROUGH = "thorough"


class CommunicationStyle(str, Enum):
    PROFESSIONAL = "professional"
    CONVERSATIONAL = "conversational"
    CONCISE = "concise"
    DETAILED = "detailed"


class RiskPosture(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class AgentIdentityProfileCreate(BaseModel):
    agent_slug: str
    role: str = "general assistant"
    mandate: Optional[str] = None
    domain_boundaries: List[str] = Field(default_factory=list)
    allowed_tool_classes: List[str] = Field(default_factory=list)
    denied_tool_classes: List[str] = Field(default_factory=list)
    escalation_threshold: EscalationThreshold = EscalationThreshold.MEDIUM
    planning_style: PlanningStyle = PlanningStyle.STEP_BY_STEP
    communication_style: CommunicationStyle = CommunicationStyle.PROFESSIONAL
    risk_posture: RiskPosture = RiskPosture.MODERATE
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    preferred_strategies: List[str] = Field(default_factory=list)
    avoided_strategies: List[str] = Field(default_factory=list)
    operating_principles: List[str] = Field(default_factory=list)
    success_criteria: List[Dict[str, Any]] = Field(default_factory=list)


class AgentIdentityProfileUpdate(BaseModel):
    role: Optional[str] = None
    mandate: Optional[str] = None
    domain_boundaries: Optional[List[str]] = None
    allowed_tool_classes: Optional[List[str]] = None
    denied_tool_classes: Optional[List[str]] = None
    escalation_threshold: Optional[EscalationThreshold] = None
    planning_style: Optional[PlanningStyle] = None
    communication_style: Optional[CommunicationStyle] = None
    risk_posture: Optional[RiskPosture] = None
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None
    preferred_strategies: Optional[List[str]] = None
    avoided_strategies: Optional[List[str]] = None
    operating_principles: Optional[List[str]] = None
    success_criteria: Optional[List[Dict[str, Any]]] = None


class AgentIdentityProfileInDB(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_slug: str
    role: str
    mandate: Optional[str] = None
    domain_boundaries: List[Any] = Field(default_factory=list)
    allowed_tool_classes: List[Any] = Field(default_factory=list)
    denied_tool_classes: List[Any] = Field(default_factory=list)
    escalation_threshold: str
    planning_style: str
    communication_style: str
    risk_posture: str
    strengths: List[Any] = Field(default_factory=list)
    weaknesses: List[Any] = Field(default_factory=list)
    preferred_strategies: List[Any] = Field(default_factory=list)
    avoided_strategies: List[Any] = Field(default_factory=list)
    operating_principles: List[Any] = Field(default_factory=list)
    success_criteria: List[Any] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
