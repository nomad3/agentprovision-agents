import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


ExternalProtocol = Literal["openai_chat", "mcp_sse", "webhook", "a2a", "copilot_extension"]
ExternalAuthType = Literal["none", "bearer", "api_key", "hmac"]


def _validate_health_check_path(v: str) -> str:
    if not v.startswith("/"):
        raise ValueError("health_check_path must start with /")
    if "//" in v or ".." in v or "@" in v:
        raise ValueError("health_check_path contains forbidden sequence")
    return v


class ExternalAgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    protocol: ExternalProtocol
    endpoint_url: str
    auth_type: ExternalAuthType = "bearer"
    credential_id: Optional[uuid.UUID] = None
    capabilities: List[str] = []
    health_check_path: str = "/health"
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("health_check_path")
    @classmethod
    def _hcp(cls, v: str) -> str:
        return _validate_health_check_path(v)


class ExternalAgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    protocol: Optional[ExternalProtocol] = None
    endpoint_url: Optional[str] = None
    auth_type: Optional[ExternalAuthType] = None
    credential_id: Optional[uuid.UUID] = None
    capabilities: Optional[List[str]] = None
    health_check_path: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("health_check_path")
    @classmethod
    def _hcp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_health_check_path(v)


class ExternalAgentInDB(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    protocol: str
    endpoint_url: str
    auth_type: str
    credential_id: Optional[uuid.UUID] = None
    capabilities: List[Any] = []
    health_check_path: str
    status: str
    last_seen_at: Optional[datetime] = None
    task_count: int
    success_count: int
    error_count: int
    avg_latency_ms: Optional[int] = None
    metadata_: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
