from pydantic import BaseModel
from typing import List, Optional
import uuid

from app.schemas.agent_skill import AgentSkill as AgentSkillSchema

class AgentBase(BaseModel):
    name: str
    description: str | None = None
    config: dict | None = None
    # Orchestration fields
    role: str | None = None  # "analyst", "manager", "specialist"
    capabilities: list[str] | None = None  # list of capability strings
    personality: dict | None = None  # dict with tone, verbosity settings
    autonomy_level: str = "supervised"  # "full", "supervised", "approval_required"
    max_delegation_depth: int = 2
    # Agent-driven runtime fields
    tool_groups: Optional[List[str]] = None
    default_model_tier: str = "full"
    persona_prompt: Optional[str] = None
    memory_domains: Optional[List[str]] = None
    escalation_agent_id: Optional[uuid.UUID] = None

class AgentCreate(AgentBase):
    pass

class AgentUpdate(AgentBase):
    pass

class Agent(AgentBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    skills: List[AgentSkillSchema] = []
    # Lifecycle fields
    status: str = "production"
    version: int = 1
    owner_user_id: Optional[uuid.UUID] = None
    team_id: Optional[uuid.UUID] = None
    successor_agent_id: Optional[uuid.UUID] = None

    class Config:
        from_attributes = True


class AgentPromoteRequest(BaseModel):
    notes: Optional[str] = None


class AgentDeprecateRequest(BaseModel):
    successor_agent_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None
