"""Pydantic schemas for MemoryActivity."""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel


class MemoryActivityCreate(BaseModel):
    event_type: str
    description: str
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    entity_id: Optional[UUID] = None
    memory_id: Optional[UUID] = None
    workflow_run_id: Optional[str] = None


class MemoryActivityInDB(MemoryActivityCreate):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class MemoryStats(BaseModel):
    total_entities: int
    total_memories: int
    total_relations: int
    pending_actions: int
    learned_today: int
