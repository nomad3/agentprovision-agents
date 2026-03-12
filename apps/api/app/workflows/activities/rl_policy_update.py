import uuid
from datetime import datetime
from temporalio import activity
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.rl_experience import RLExperience
from app.models.rl_policy_state import RLPolicyState
from app.models.tenant_features import TenantFeatures
from app.services import rl_experience_service


@activity.defn
async def collect_tenant_experiences(tenant_id: str) -> dict:
    """Collect experience statistics for a tenant."""
    db = SessionLocal()
    try:
        tid = uuid.UUID(tenant_id)
        stats = (
            db.query(
                RLExperience.decision_point,
                func.count(RLExperience.id).label("count"),
                func.avg(RLExperience.reward).label("avg_reward"),
            )
            .filter(
                RLExperience.tenant_id == tid,
                RLExperience.archived_at.is_(None),
                RLExperience.reward.isnot(None),
            )
            .group_by(RLExperience.decision_point)
            .all()
        )
        return {
            "tenant_id": tenant_id,
            "decision_points": {
                s.decision_point: {"count": s.count, "avg_reward": float(s.avg_reward or 0)}
                for s in stats
            },
        }
    finally:
        db.close()


@activity.defn
async def update_tenant_policy(tenant_id: str, decision_point: str) -> dict:
    """Recompute policy weights for a tenant+decision_point from all rewarded experiences."""
    db = SessionLocal()
    try:
        tid = uuid.UUID(tenant_id)
        experiences = (
            db.query(RLExperience)
            .filter(
                RLExperience.tenant_id == tid,
                RLExperience.decision_point == decision_point,
                RLExperience.reward.isnot(None),
                RLExperience.archived_at.is_(None),
            )
            .all()
        )

        if not experiences:
            return {"tenant_id": tenant_id, "decision_point": decision_point, "updated": False}

        # Compute action-level aggregate scores
        action_scores = {}
        for exp in experiences:
            action_key = str(exp.action.get("id", exp.action.get("name", "unknown")))
            if action_key not in action_scores:
                action_scores[action_key] = {"total_reward": 0, "count": 0}
            action_scores[action_key]["total_reward"] += exp.reward
            action_scores[action_key]["count"] += 1

        weights = {
            k: {"avg_reward": v["total_reward"] / v["count"], "count": v["count"]}
            for k, v in action_scores.items()
        }

        policy = (
            db.query(RLPolicyState)
            .filter(RLPolicyState.tenant_id == tid, RLPolicyState.decision_point == decision_point)
            .first()
        )

        if policy:
            old_version = int(policy.version.replace("v", "")) if policy.version.startswith("v") else 0
            policy.weights = weights
            policy.version = f"v{old_version + 1}"
            policy.experience_count = len(experiences)
            policy.last_updated_at = datetime.utcnow()
        else:
            policy = RLPolicyState(
                tenant_id=tid,
                decision_point=decision_point,
                weights=weights,
                version="v1",
                experience_count=len(experiences),
            )
            db.add(policy)

        db.commit()
        return {"tenant_id": tenant_id, "decision_point": decision_point, "updated": True, "version": policy.version}
    finally:
        db.close()


@activity.defn
async def anonymize_and_aggregate_global(decision_point: str) -> dict:
    """Aggregate anonymized experience data from opt-in tenants into global baseline."""
    db = SessionLocal()
    try:
        opt_in_tenants = (
            db.query(TenantFeatures)
            .filter(TenantFeatures.rl_enabled == True)
            .all()
        )
        opt_in_ids = [
            f.tenant_id for f in opt_in_tenants
            if f.rl_settings and f.rl_settings.get("opt_in_global_learning", True)
        ]

        if not opt_in_ids:
            return {"decision_point": decision_point, "updated": False}

        experiences = (
            db.query(RLExperience)
            .filter(
                RLExperience.tenant_id.in_(opt_in_ids),
                RLExperience.decision_point == decision_point,
                RLExperience.reward.isnot(None),
                RLExperience.archived_at.is_(None),
            )
            .all()
        )

        action_scores = {}
        for exp in experiences:
            action_key = str(exp.action.get("id", exp.action.get("name", "unknown")))
            if action_key not in action_scores:
                action_scores[action_key] = {"total_reward": 0, "count": 0}
            action_scores[action_key]["total_reward"] += exp.reward
            action_scores[action_key]["count"] += 1

        weights = {
            k: {"avg_reward": v["total_reward"] / v["count"], "count": v["count"]}
            for k, v in action_scores.items()
        }

        global_policy = (
            db.query(RLPolicyState)
            .filter(RLPolicyState.tenant_id.is_(None), RLPolicyState.decision_point == decision_point)
            .first()
        )
        if global_policy:
            old_ver = int(global_policy.version.replace("v", "")) if global_policy.version.startswith("v") else 0
            global_policy.weights = weights
            global_policy.version = f"v{old_ver + 1}"
            global_policy.experience_count = len(experiences)
            global_policy.last_updated_at = datetime.utcnow()
        else:
            global_policy = RLPolicyState(
                tenant_id=None,
                decision_point=decision_point,
                weights=weights,
                version="v1",
                experience_count=len(experiences),
            )
            db.add(global_policy)

        db.commit()
        return {"decision_point": decision_point, "updated": True, "tenants": len(opt_in_ids)}
    finally:
        db.close()


@activity.defn
async def archive_old_experiences(tenant_id: str, retention_days: int = 90) -> dict:
    """Archive experiences beyond retention window."""
    db = SessionLocal()
    try:
        count = rl_experience_service.archive_old_experiences(db, uuid.UUID(tenant_id), retention_days)
        return {"tenant_id": tenant_id, "archived": count}
    finally:
        db.close()
