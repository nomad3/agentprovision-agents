"""Bulk ingestion entry point — receives MemoryEvents from source adapters."""
from uuid import UUID
from sqlalchemy.orm import Session
from app.memory.types import MemoryEvent


def ingest_events(
    db: Session,
    tenant_id: UUID,
    events: list[MemoryEvent],
    workflow_id: str | None = None,
):
    """Implementation in Task 15."""
    raise NotImplementedError("Task 15 implements this")
