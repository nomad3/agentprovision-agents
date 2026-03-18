from typing import List, Dict, Any

from pydantic import BaseModel, Field
import uuid


class AgentKitToolBinding(BaseModel):
    tool_id: uuid.UUID
    alias: str = Field(..., description="Short handle used inside playbooks")
    capabilities: List[str] = Field(default_factory=list)


class AgentKitVectorBinding(BaseModel):
    vector_store_id: uuid.UUID
    use_case: str
    filters: Dict[str, Any] | None = None


class AgentKitPlaybookStep(BaseModel):
    name: str
    description: str
    agent_action: str
    tool_aliases: List[str] = Field(default_factory=list)
    vector_use_cases: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    notes: str | None = None


class AgentKitConfig(BaseModel):
    primary_objective: str = ""
    skill_slug: str | None = None  # Maps kit to a skill directory for CLI routing
    triggers: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    tool_bindings: List[AgentKitToolBinding] = Field(default_factory=list)
    vector_bindings: List[AgentKitVectorBinding] = Field(default_factory=list)
    playbook: List[AgentKitPlaybookStep] = Field(default_factory=list)
    handoff_channels: List[str] = Field(default_factory=list)


class AgentKitBase(BaseModel):
    name: str
    description: str | None = None
    version: str | None = None
    config: AgentKitConfig
    scoring_rubric: Dict[str, Any] | None = None

class AgentKitCreate(AgentKitBase):
    pass

class AgentKitUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    version: str | None = None
    config: AgentKitConfig | None = None
    scoring_rubric: Dict[str, Any] | None = None

class AgentKit(AgentKitBase):
    id: uuid.UUID
    tenant_id: uuid.UUID

    class Config:
        from_attributes = True


class ResolvedToolBinding(BaseModel):
    id: uuid.UUID
    alias: str
    name: str
    description: str | None = None
    capabilities: List[str] = Field(default_factory=list)
    config: Dict[str, Any] | None = None


class ResolvedVectorBinding(BaseModel):
    id: uuid.UUID
    use_case: str
    name: str
    description: str | None = None
    provider: str | None = None
    config: Dict[str, Any] | None = None


class AgentKitSimulationStep(BaseModel):
    order: int
    name: str
    agent_action: str
    summary: str
    tools: List[ResolvedToolBinding] = Field(default_factory=list)
    vector_context: List[ResolvedVectorBinding] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    recommended_prompt: str | None = None


class AgentKitSimulation(BaseModel):
    agent_kit_id: uuid.UUID
    objective: str
    metrics: List[str]
    constraints: List[str]
    resolved_tools: List[ResolvedToolBinding]
    resolved_vector_stores: List[ResolvedVectorBinding]
    steps: List[AgentKitSimulationStep]
    next_actions: List[str] = Field(default_factory=list)
