"""Pydantic schemas for AgentMemory"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class AgentMemoryBase(BaseModel):
    """Base schema for AgentMemory"""
    memory_type: str = Field(..., description="Type: fact, experience, skill, preference, relationship, procedure")
    content: str = Field(..., min_length=1, description="Memory content")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score 0-1")
    source: Optional[str] = Field(None, description="Source of the memory")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")


class AgentMemoryCreate(AgentMemoryBase):
    """Schema for creating a memory"""
    agent_id: UUID
    embedding: Optional[List[float]] = Field(None, description="Vector embedding")
    source_task_id: Optional[UUID] = None


class AgentMemoryUpdate(BaseModel):
    """Schema for updating a memory"""
    content: Optional[str] = None
    importance: Optional[float] = Field(None, ge=0.0, le=1.0)
    embedding: Optional[List[float]] = None
    expires_at: Optional[datetime] = None


class AgentMemoryInDB(AgentMemoryBase):
    """Schema for memory from database"""
    id: UUID
    agent_id: UUID
    tenant_id: UUID
    embedding: Optional[List[float]] = None
    access_count: int
    source_task_id: Optional[UUID] = None
    created_at: datetime
    last_accessed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentMemoryResponse(AgentMemoryInDB):
    """Schema for API response"""
    pass


class SpatialMemoryResponse(BaseModel):
    id: UUID
    content_type: str
    text_content: str
    embedding: List[float]
    created_at: datetime

    class Config:
        from_attributes = True
