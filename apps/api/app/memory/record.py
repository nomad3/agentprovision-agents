"""Synchronous memory write operations.

These are the SMALL, FAST writes that happen on the request thread:
single observation, single commitment, single goal. Bulk writes go
through `ingest_events()` which is async via Temporal.
"""
from uuid import UUID
from sqlalchemy.orm import Session


def record_observation(db: Session, tenant_id: UUID, **kwargs):
    """Implementation in Task 14."""
    raise NotImplementedError("Task 14 implements this")


def record_commitment(db: Session, tenant_id: UUID, **kwargs):
    """Implementation in Task 14."""
    raise NotImplementedError("Task 14 implements this")


def record_goal(db: Session, tenant_id: UUID, **kwargs):
    """Implementation in Task 14."""
    raise NotImplementedError("Task 14 implements this")
