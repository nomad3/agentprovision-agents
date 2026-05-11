from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, field_validator

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

    # Null-tolerant validators. Legacy agent rows sometimes carry stray
    # `null` entries in the JSONB array (e.g. tool_groups: [null, "meta"]
    # from a half-applied backfill). Pydantic's default `List[str]` then
    # rejects the whole agent at serialize-time, which crashes
    # GET /api/v1/agents (FastAPI 500 → ResponseValidationError →
    # 'tool_groups[0]': Input should be a valid string). We strip nulls
    # transparently here so the read path is resilient; the migration
    # 124 added 2026-05-11 cleans the existing data, but the validator
    # is the long-term guard.
    @field_validator("tool_groups", "memory_domains", "capabilities", mode="before")
    @classmethod
    def _strip_nulls_in_string_list(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return [x for x in v if x is not None]
        return v

class AgentCreate(AgentBase):
    status: str = "draft"

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


class AgentImportRequest(BaseModel):
    content: str
    filename: str = "agent.yaml"


class AgentPromoteRequest(BaseModel):
    notes: Optional[str] = None
    # Opt-out for teams that haven't written tests yet. Default False keeps the
    # gate enabled — callers must explicitly bypass the regression check.
    skip_tests: bool = False


class AgentDeprecateRequest(BaseModel):
    successor_agent_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class AgentVersionResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    tenant_id: uuid.UUID
    version: int
    config_snapshot: Dict[str, Any]
    status: str
    notes: Optional[str] = None
    promoted_by: Optional[uuid.UUID] = None
    promoted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
