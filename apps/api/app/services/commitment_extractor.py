"""
Commitment extractor — DISABLED.

Auto-extraction of commitments from Luna's responses via regex was removed
because:
  1. Patterns were always either too broad (extracting third-person
     descriptions) or too narrow (missing genuine commitments).
  2. Extracted fragments polluted Luna's system prompt and caused
     self-referential loops (Luna explaining Gap 3 → extractor creates
     "Gap 3" commitment → next prompt includes it → Luna explains Gap 3
     again).
  3. We already have RL + embeddings + knowledge graph for proper
     context management. Regex-matching LLM output is the wrong layer.

Proper path forward: Luna creates commitments via explicit tool calls
(commitments API) when she decides to, and they're recalled via semantic
search on the knowledge graph when relevant.

This module now exposes no-op stubs for the legacy callers.
"""

import logging
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.commitment_record import CommitmentRecord

logger = logging.getLogger(__name__)


def extract_commitments_from_response(
    db: Session,
    tenant_id: uuid.UUID,
    response_text: str,
    message_id: Optional[uuid.UUID] = None,
    session_id: Optional[uuid.UUID] = None,
    agent_slug: str = "luna",
) -> List[CommitmentRecord]:
    """No-op. Auto-extraction disabled — see module docstring."""
    return []


def build_stakes_context(db: Session, tenant_id: uuid.UUID) -> str:
    """No-op. Stakes context is no longer injected into every system prompt.

    Commitment awareness should flow through semantic recall on demand,
    not via hardcoded injection on every message.
    """
    return ""


def get_commitment_stats(db: Session, tenant_id: uuid.UUID, days: int = 30) -> dict:
    """Return actual stats from the DB (no extraction, just counts)."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = db.query(CommitmentRecord).filter(
        CommitmentRecord.tenant_id == tenant_id,
        CommitmentRecord.created_at >= cutoff,
    ).all()
    if not rows:
        return {}
    fulfilled = sum(1 for c in rows if c.state == "fulfilled")
    broken = sum(1 for c in rows if c.state == "broken")
    open_count = sum(1 for c in rows if c.state == "open")
    total = len(rows)
    return {
        "total": total,
        "fulfilled": fulfilled,
        "broken": broken,
        "open": open_count,
        "fulfillment_rate": round(fulfilled / total, 2) if total else 0,
    }
