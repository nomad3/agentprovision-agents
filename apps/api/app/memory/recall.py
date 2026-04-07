"""Memory recall — pre-loads context for the chat hot path.

This module is the entry point for all recall operations. The hot path
calls `recall()` ONCE per chat turn before dispatching to the CLI;
no in-prompt "recall tool" exists in this design.
"""
from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.memory.types import RecallRequest, RecallResponse


def recall(
    db: Session,
    tenant_id: UUID,
    agent_slug: str,
    query: str,
    *,
    chat_session_id: Optional[UUID] = None,
    top_k_per_type: int = 5,
    total_token_budget: int = 8000,
    source_filter: Optional[list[str]] = None,
) -> RecallResponse:
    """Pre-load memory context for a chat turn. Implementation in Task 10."""
    raise NotImplementedError("Task 10 implements this")
