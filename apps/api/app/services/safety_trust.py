"""Trust scoring and autonomy-tier assignment for agent execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.safety_policy import AgentTrustProfile
from app.schemas.safety_policy import AutonomyTier

DEFAULT_TRUST_SCORE = 0.5


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize_reward(avg_reward: Optional[float]) -> float:
    if avg_reward is None:
        return DEFAULT_TRUST_SCORE
    if avg_reward < 0:
        return _clamp((avg_reward + 1.0) / 2.0)
    return _clamp(avg_reward)


def _derive_autonomy_tier(trust_score: float, confidence: float) -> AutonomyTier:
    if confidence < 0.2 or trust_score < 0.35:
        return AutonomyTier.OBSERVE_ONLY
    if trust_score < 0.55:
        return AutonomyTier.RECOMMEND_ONLY
    if trust_score < 0.8:
        return AutonomyTier.SUPERVISED_EXECUTION
    return AutonomyTier.BOUNDED_AUTONOMOUS_EXECUTION


def _query_agent_reward_stats(
    db: Session,
    tenant_id: uuid.UUID,
    agent_slug: str,
) -> Dict[str, Any]:
    sql = text(
        """
        SELECT
            COUNT(*) FILTER (WHERE reward IS NOT NULL) AS rated_count,
            AVG(reward) FILTER (WHERE reward IS NOT NULL) AS avg_reward
        FROM rl_experiences
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND archived_at IS NULL
          AND COALESCE(action->>'agent_slug', state->>'agent_slug') = :agent_slug
        """
    )
    row = db.execute(
        sql,
        {"tenant_id": str(tenant_id), "agent_slug": agent_slug},
    ).one()
    return {
        "rated_count": int(row.rated_count or 0),
        "avg_reward": float(row.avg_reward) if row.avg_reward is not None else None,
    }


def _query_provider_council_signal(
    db: Session,
    tenant_id: uuid.UUID,
    agent_slug: str,
) -> Dict[str, Any]:
    sql = text(
        """
        SELECT reward_components
        FROM rl_experiences
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND archived_at IS NULL
          AND COALESCE(action->>'agent_slug', state->>'agent_slug') = :agent_slug
          AND reward_components ? 'provider_council'
        """
    )
    rows = db.execute(
        sql,
        {"tenant_id": str(tenant_id), "agent_slug": agent_slug},
    ).fetchall()

    agreements: List[float] = []
    for row in rows:
        payload = (row.reward_components or {}).get("provider_council", {})
        agreement = payload.get("agreement")
        if agreement is not None:
            try:
                agreements.append(float(agreement))
            except (TypeError, ValueError):
                continue

    if not agreements:
        return {
            "provider_review_count": 0,
            "provider_signal": DEFAULT_TRUST_SCORE,
        }

    avg_agreement = sum(agreements) / len(agreements)
    return {
        "provider_review_count": len(agreements),
        "provider_signal": _clamp(avg_agreement),
    }


def recompute_agent_trust_profile(
    db: Session,
    tenant_id: uuid.UUID,
    agent_slug: str,
) -> AgentTrustProfile:
    reward_stats = _query_agent_reward_stats(db, tenant_id, agent_slug)
    provider_stats = _query_provider_council_signal(db, tenant_id, agent_slug)

    reward_signal = _normalize_reward(reward_stats["avg_reward"])
    provider_signal = provider_stats["provider_signal"]
    rated_count = reward_stats["rated_count"]
    provider_review_count = provider_stats["provider_review_count"]
    confidence = _clamp((rated_count / 25.0) * 0.7 + (provider_review_count / 10.0) * 0.3)
    if rated_count == 0 and provider_review_count == 0:
        confidence = 0.0

    trust_score = _clamp(
        (reward_signal * 0.7 + provider_signal * 0.3) * confidence
        + DEFAULT_TRUST_SCORE * (1.0 - confidence)
    )
    autonomy_tier = _derive_autonomy_tier(trust_score, confidence)
    rationale = (
        f"reward_signal={reward_signal:.3f} over {rated_count} rated experiences; "
        f"provider_signal={provider_signal:.3f} over {provider_review_count} provider councils; "
        f"confidence={confidence:.3f}"
    )

    profile = (
        db.query(AgentTrustProfile)
        .filter(
            AgentTrustProfile.tenant_id == tenant_id,
            AgentTrustProfile.agent_slug == agent_slug,
        )
        .first()
    )
    if not profile:
        profile = AgentTrustProfile(
            tenant_id=tenant_id,
            agent_slug=agent_slug,
        )
        db.add(profile)

    profile.trust_score = round(trust_score, 3)
    profile.confidence = round(confidence, 3)
    profile.autonomy_tier = autonomy_tier.value
    profile.reward_signal = round(reward_signal, 3)
    profile.provider_signal = round(provider_signal, 3)
    profile.rated_experience_count = rated_count
    profile.provider_review_count = provider_review_count
    profile.rationale = rationale
    profile.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(profile)
    return profile


def get_agent_trust_profile(
    db: Session,
    tenant_id: uuid.UUID,
    agent_slug: Optional[str],
    *,
    auto_create: bool = True,
) -> Optional[AgentTrustProfile]:
    if not agent_slug:
        return None

    profile = (
        db.query(AgentTrustProfile)
        .filter(
            AgentTrustProfile.tenant_id == tenant_id,
            AgentTrustProfile.agent_slug == agent_slug,
        )
        .first()
    )
    if profile or not auto_create:
        return profile
    return recompute_agent_trust_profile(db, tenant_id, agent_slug)


def list_agent_trust_profiles(
    db: Session,
    tenant_id: uuid.UUID,
) -> List[AgentTrustProfile]:
    return (
        db.query(AgentTrustProfile)
        .filter(AgentTrustProfile.tenant_id == tenant_id)
        .order_by(AgentTrustProfile.trust_score.desc(), AgentTrustProfile.updated_at.desc())
        .all()
    )

