"""Reliability shim around ExternalAgentAdapter.dispatch.

Wraps each external dispatch with:
  * Per-protocol timeout (default 30s, override via metadata_['timeout']).
  * Exponential backoff retry — 3 attempts, coefficient 2 — matching the
    Temporal RetryPolicy(maximum_attempts=3) semantics that
    coalition_workflow.py:27 already uses, so the platform's retry
    vocabulary stays uniform.
  * Redis-backed circuit breaker keyed on ``agent:breaker:{external_agent_id}``.
    Open after 5 consecutive failures; auto half-open after 60s; one
    successful probe closes it.
  * Optional fallback dispatch to another external agent specified in
    ``metadata_['fallback_agent_id']`` (depth 1, no recursion).

Surfaces breaker state in ``external_agents.status``:
``online | busy | error | breaker_open``.

Design notes:
  * Sync entrypoint to match the rest of the adapter and chat path.
  * Redis is optional — if unavailable, the breaker degrades to no-op
    (just retry). The native side already handles this pattern (see
    AgentRegistry._get_redis).
  * The retry loop is intentionally simple — no jitter, no per-error
    classification — because external-agent dispatch is low-frequency
    relative to the rest of the platform. If volume grows we can swap
    in tenacity.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.external_agent import ExternalAgent

logger = logging.getLogger(__name__)


# Tunables — match Temporal's RetryPolicy defaults so the vocabulary is
# the same across native (Temporal activity) and external (this shim).
MAX_ATTEMPTS = 3
BACKOFF_INITIAL_S = 1.0
BACKOFF_COEFFICIENT = 2.0

BREAKER_THRESHOLD = 5
BREAKER_OPEN_SECONDS = 60

_BREAKER_KEY_FMT = "agent:breaker:{external_agent_id}"
_FAIL_COUNT_KEY_FMT = "agent:breaker:fails:{external_agent_id}"


# ---------------------------------------------------------------------------
# Redis client (optional)
# ---------------------------------------------------------------------------

_redis_client = None


def _get_redis():
    """Best-effort Redis client. Mirrors AgentRegistry._get_redis so we
    don't fight over connection pools or import order.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        _redis_client = redis_lib.from_url(settings.REDIS_URL)
        return _redis_client
    except Exception as exc:
        logger.warning("external_agent_reliability: Redis connect failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

def _breaker_is_open(agent_id) -> bool:
    r = _get_redis()
    if r is None:
        return False
    try:
        return bool(r.exists(_BREAKER_KEY_FMT.format(external_agent_id=str(agent_id))))
    except Exception as exc:
        logger.warning("breaker check failed for %s: %s", agent_id, exc)
        return False


def _record_failure(agent_id) -> int:
    """Increment the consecutive-failure counter; trip the breaker once
    BREAKER_THRESHOLD is reached. Returns the new failure count.
    """
    r = _get_redis()
    if r is None:
        return 0
    key = _FAIL_COUNT_KEY_FMT.format(external_agent_id=str(agent_id))
    try:
        count = int(r.incr(key))
        # Counter expires alongside the breaker so we don't carry old
        # failures forever after a long quiet period.
        r.expire(key, BREAKER_OPEN_SECONDS * 4)
        if count >= BREAKER_THRESHOLD:
            r.set(
                _BREAKER_KEY_FMT.format(external_agent_id=str(agent_id)),
                "1",
                ex=BREAKER_OPEN_SECONDS,
            )
        return count
    except Exception as exc:
        logger.warning("breaker record failure for %s: %s", agent_id, exc)
        return 0


def _record_success(agent_id) -> None:
    """A successful call closes the breaker and zeroes the failure counter."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(
            _BREAKER_KEY_FMT.format(external_agent_id=str(agent_id)),
            _FAIL_COUNT_KEY_FMT.format(external_agent_id=str(agent_id)),
        )
    except Exception as exc:
        logger.warning("breaker record success for %s: %s", agent_id, exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def external_agent_call(
    agent: ExternalAgent,
    task: str,
    context: dict,
    db: Session,
    *,
    _depth: int = 0,
) -> str:
    """Reliable wrapper around ExternalAgentAdapter.dispatch.

    Honors retry, circuit breaker, and optional fallback. Updates
    ``agent.status`` so the discovery surface reflects current health.
    """
    # Avoid a circular import — adapter pulls credential vault which
    # pulls Session; this module also uses Session.
    from app.services.external_agent_adapter import adapter

    if _depth > 1:
        raise RuntimeError("fallback recursion exceeded")

    if _breaker_is_open(agent.id):
        agent.status = "breaker_open"
        db.add(agent)
        db.commit()
        fallback = _resolve_fallback(agent, db)
        if fallback is not None:
            logger.info(
                "external_agent_call: breaker open for %s, dispatching to fallback %s",
                agent.id, fallback.id,
            )
            return external_agent_call(fallback, task, context, db, _depth=_depth + 1)
        raise RuntimeError(
            f"External agent {agent.name} circuit breaker is open and no fallback is configured."
        )

    last_exc: Optional[Exception] = None
    delay = BACKOFF_INITIAL_S
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = adapter.dispatch(agent, task, context, db)
            _mark_online(agent, db)
            _record_success(agent.id)
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "external_agent_call: %s attempt %d/%d failed: %s",
                agent.id, attempt, MAX_ATTEMPTS, exc,
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(delay)
                delay *= BACKOFF_COEFFICIENT

    # All attempts failed — record a hard failure and consider fallback.
    _record_failure(agent.id)
    _mark_error(agent, db)
    fallback = _resolve_fallback(agent, db)
    if fallback is not None:
        logger.info(
            "external_agent_call: %s exhausted retries, dispatching to fallback %s",
            agent.id, fallback.id,
        )
        return external_agent_call(fallback, task, context, db, _depth=_depth + 1)
    if isinstance(last_exc, RuntimeError):
        raise last_exc
    raise RuntimeError(f"external dispatch to {agent.name} failed: {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_fallback(agent: ExternalAgent, db: Session) -> Optional[ExternalAgent]:
    fallback_id = (agent.metadata_ or {}).get("fallback_agent_id")
    if not fallback_id:
        return None
    try:
        import uuid
        return (
            db.query(ExternalAgent)
            .filter(ExternalAgent.id == uuid.UUID(str(fallback_id)))
            .first()
        )
    except Exception:
        return None


def _mark_online(agent: ExternalAgent, db: Session) -> None:
    if agent.status != "online":
        agent.status = "online"
        db.add(agent)
        db.commit()


def _mark_error(agent: ExternalAgent, db: Session) -> None:
    agent.status = "error"
    db.add(agent)
    db.commit()
