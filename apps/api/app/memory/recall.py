"""Memory recall — pre-loads context for the chat hot path.

This module is the entry point for all recall operations. The hot path
calls `recall()` ONCE per chat turn before dispatching to the CLI;
no in-prompt "recall tool" exists in this design.

Signature takes a RecallRequest dataclass (mirrors the gRPC IDL exactly)
so Phase 2 cutover to a Rust gRPC client is a no-op for callers.
"""
from sqlalchemy.orm import Session
from app.memory.types import RecallRequest, RecallResponse


def recall(db: Session, request: RecallRequest) -> RecallResponse:
    """Pre-load memory context for a chat turn.

    Args:
        db: SQLAlchemy session bound to the canonical Postgres.
        request: RecallRequest dataclass with tenant_id, agent_slug, query,
                 and optional knobs (top_k_per_type, total_token_budget,
                 chat_session_id, source_filter).

    Returns:
        RecallResponse with entities, observations, relations, commitments,
        goals, past_conversations, episodes, contradictions, plus metadata
        (elapsed_ms, used_keyword_fallback, degraded, truncated_for_budget).

    Implementation in Plan Task 10 — currently a stub.
    """
    raise NotImplementedError("Task 10 implements this")
