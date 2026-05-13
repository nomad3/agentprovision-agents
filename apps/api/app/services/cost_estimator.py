"""Cost + duration estimator for `ap run` dispatches.

Replaces the hardcoded `0.12 * n_providers` placeholder in
`apps/api/app/api/v1/tasks_fanout.py` with a real SQL aggregation
over historical `chat_messages.cost_usd` per provider / per tenant.

The estimator is intentionally simple — it does NOT do
RL-state-embedding retrieval (the design target for
`rl_experience_service.estimate_for_state`, which doesn't exist
yet). Instead it averages cost + duration over the last N
completed chat messages for this tenant that ran on a model
matching each requested provider. That's good enough to replace
the static placeholder; richer per-state retrieval is a
follow-up when RL experience search is ready.

Falls back to the previous static placeholder when the tenant has
zero historical data — new tenants and first-use providers stay
predictable.

Tenant isolation: every query filters on `tenant_id`; this module
is import-safe from any route handler that already has the JWT-
bound tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession


# Static fallback. Matches the prior placeholder in tasks_fanout.py.
_FALLBACK_COST_PER_PROVIDER_USD = 0.12
_FALLBACK_DURATION_SECONDS = 30
_FALLBACK_CONFIDENCE = "low"

# Confidence thresholds.
_HIGH_CONFIDENCE_SAMPLES = 5
_MEDIUM_CONFIDENCE_SAMPLES = 1

# Maps a CLI-platform identifier to one or more chat_messages.model
# prefixes. Producers (cli_session_manager / chat hot path) store the
# concrete model id in `chat_messages.model`; we match by prefix so
# minor version bumps (e.g. claude-sonnet-4-6 → 4-7) don't reset the
# tenant's cost history.
_PROVIDER_MODEL_PREFIXES: dict[str, list[str]] = {
    "claude": ["claude-"],
    "codex": ["gpt-", "codex-", "o1-", "o3-"],
    "gemini": ["gemini-"],
    "copilot": ["copilot-", "github-copilot-"],
    "opencode": ["gemma", "ollama", "qwen", "deepseek"],
}


@dataclass
class CostEstimate:
    """Estimator output. Mirrors the shape of `tasks_fanout.RunEstimate`
    so the route can construct the response directly."""

    estimated_cost_usd: float
    estimated_duration_seconds: int
    confidence: str  # "low" | "medium" | "high"


def estimate_fanout_cost(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    providers: Iterable[str],
    sample_limit: int = 50,
) -> CostEstimate:
    """Estimate the total cost + duration of dispatching to N providers
    in parallel, using historical chat_messages for this tenant.

    Args:
      db: SQLAlchemy session.
      tenant_id: Tenant whose history we read. Caller passes the JWT-
        bound value; we do not accept untrusted input.
      providers: Iterable of provider identifiers ("claude", "codex",
        "gemini", ...). Order does not matter. Empty list → falls
        back to placeholder for a single-provider dispatch.
      sample_limit: Per-provider history cap. Cheap default keeps the
        query under a few KB even for active tenants.

    Returns:
      CostEstimate with `confidence` reflecting how much historical
      data backed the number ("low" = none, "medium" = ≥1 sample on
      any provider, "high" = ≥5 samples on every provider).
    """

    provider_list = [p.strip() for p in providers if p and p.strip()]
    n = max(len(provider_list), 1)

    if not provider_list:
        return CostEstimate(
            estimated_cost_usd=_FALLBACK_COST_PER_PROVIDER_USD,
            estimated_duration_seconds=_FALLBACK_DURATION_SECONDS,
            confidence=_FALLBACK_CONFIDENCE,
        )

    total_cost = 0.0
    max_duration = 0  # parallel dispatch → wallclock is the slowest child
    sample_counts: list[int] = []

    for provider in provider_list:
        prefixes = _PROVIDER_MODEL_PREFIXES.get(provider, [provider + "-"])
        per_provider_cost, per_provider_duration, samples = _aggregate_for_provider(
            db,
            tenant_id=tenant_id,
            prefixes=prefixes,
            sample_limit=sample_limit,
        )
        if samples == 0:
            # Fall back to the per-provider placeholder for this slot;
            # tally as a zero-sample contribution so confidence drops.
            per_provider_cost = _FALLBACK_COST_PER_PROVIDER_USD
            per_provider_duration = _FALLBACK_DURATION_SECONDS
        total_cost += per_provider_cost
        max_duration = max(max_duration, per_provider_duration)
        sample_counts.append(samples)

    # Confidence ladder.
    if all(c >= _HIGH_CONFIDENCE_SAMPLES for c in sample_counts):
        confidence = "high"
    elif any(c >= _MEDIUM_CONFIDENCE_SAMPLES for c in sample_counts):
        confidence = "medium"
    else:
        confidence = "low"

    return CostEstimate(
        estimated_cost_usd=round(total_cost, 4),
        estimated_duration_seconds=max_duration or _FALLBACK_DURATION_SECONDS,
        confidence=confidence,
    )


def _aggregate_for_provider(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    prefixes: list[str],
    sample_limit: int,
) -> tuple[float, int, int]:
    """Average cost_usd + a rough duration proxy over recent
    chat_messages for the given tenant whose `model` starts with any
    of the supplied prefixes. Returns (avg_cost, avg_duration, n_samples).

    Duration is approximated from `tokens_used` × a per-provider
    seconds-per-1000-tokens constant. We don't have a real elapsed-
    time field on chat_messages; the proxy is rough but better than
    the static 30s placeholder for tenants with history. The
    follow-up RL retrieval will replace this with measured elapsed."""

    # Build the model-prefix OR clause via ilike.
    from sqlalchemy import or_

    prefix_clauses = [ChatMessage.model.ilike(f"{p}%") for p in prefixes]

    # Limit-then-aggregate via a subquery so we cap the number of rows
    # we average over (sample_limit). Old runs shouldn't drown out
    # recent pricing changes.
    base_query = (
        db.query(
            ChatMessage.cost_usd,
            ChatMessage.tokens_used,
        )
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .filter(ChatSession.tenant_id == tenant_id)
        .filter(ChatMessage.role == "assistant")
        .filter(ChatMessage.cost_usd.isnot(None))
        .filter(or_(*prefix_clauses))
        .order_by(ChatMessage.created_at.desc())
        .limit(sample_limit)
    )

    rows = base_query.all()
    if not rows:
        return (0.0, 0, 0)

    costs = [float(r.cost_usd) for r in rows if r.cost_usd is not None]
    tokens = [int(r.tokens_used) for r in rows if r.tokens_used]

    if not costs:
        return (0.0, 0, 0)

    avg_cost = sum(costs) / len(costs)
    avg_tokens = (sum(tokens) / len(tokens)) if tokens else 0
    # Crude proxy: 1000 tokens ≈ 5 seconds wallclock. Replaced by
    # measured elapsed when RL retrieval lands.
    avg_duration = int(max(5, (avg_tokens / 1000.0) * 5))

    return (avg_cost, avg_duration, len(costs))
