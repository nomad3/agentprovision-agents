"""Learning dashboard service — surfaces policy improvement insights."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.models.learning_experiment import LearningExperiment, PolicyCandidate
from app.models.rl_experience import RLExperience

logger = logging.getLogger(__name__)


def get_policy_improvement_summary(
    db: Session,
    tenant_id: uuid.UUID,
) -> Dict[str, Any]:
    """Show which policies improved — promoted candidates with their impact."""
    promoted = (
        db.query(PolicyCandidate)
        .filter(
            PolicyCandidate.tenant_id == tenant_id,
            PolicyCandidate.status == "promoted",
        )
        .order_by(PolicyCandidate.promoted_at.desc())
        .limit(20)
        .all()
    )

    improvements = []
    for c in promoted:
        experiment = (
            db.query(LearningExperiment)
            .filter(
                LearningExperiment.candidate_id == c.id,
                LearningExperiment.status == "completed",
                LearningExperiment.is_significant == "yes",
            )
            .order_by(LearningExperiment.completed_at.desc())
            .first()
        )
        improvements.append({
            "candidate_id": str(c.id),
            "policy_type": c.policy_type,
            "decision_point": c.decision_point,
            "description": c.description,
            "promoted_at": c.promoted_at.isoformat() if c.promoted_at else None,
            "baseline_reward": c.baseline_reward,
            "expected_improvement": c.expected_improvement,
            "actual_improvement_pct": experiment.improvement_pct if experiment else None,
            "treatment_avg_reward": experiment.treatment_avg_reward if experiment else None,
            "control_avg_reward": experiment.control_avg_reward if experiment else None,
        })

    rejected = (
        db.query(func.count(PolicyCandidate.id))
        .filter(PolicyCandidate.tenant_id == tenant_id, PolicyCandidate.status == "rejected")
        .scalar()
    )

    total = (
        db.query(func.count(PolicyCandidate.id))
        .filter(PolicyCandidate.tenant_id == tenant_id)
        .scalar()
    )

    promoted_count = (
        db.query(func.count(PolicyCandidate.id))
        .filter(PolicyCandidate.tenant_id == tenant_id, PolicyCandidate.status == "promoted")
        .scalar()
    )

    return {
        "total_candidates": total,
        "promoted_count": promoted_count,
        "rejected_count": rejected,
        "improvements": improvements,
    }


def get_learning_stalls(
    db: Session,
    tenant_id: uuid.UUID,
    stale_days: int = 14,
) -> Dict[str, Any]:
    """Show where learning is stalled — decision points with no recent improvement."""
    cutoff = datetime.utcnow() - timedelta(days=stale_days)

    # Decision points with candidates but no recent promotion
    all_decision_points = (
        db.query(PolicyCandidate.decision_point, func.count(PolicyCandidate.id).label("total"))
        .filter(PolicyCandidate.tenant_id == tenant_id)
        .group_by(PolicyCandidate.decision_point)
        .all()
    )

    stalled = []
    active = []
    for row in all_decision_points:
        dp = row.decision_point
        recent_promotion = (
            db.query(PolicyCandidate)
            .filter(
                PolicyCandidate.tenant_id == tenant_id,
                PolicyCandidate.decision_point == dp,
                PolicyCandidate.status == "promoted",
                PolicyCandidate.promoted_at > cutoff,
            )
            .first()
        )

        pending = (
            db.query(func.count(PolicyCandidate.id))
            .filter(
                PolicyCandidate.tenant_id == tenant_id,
                PolicyCandidate.decision_point == dp,
                PolicyCandidate.status.in_(["proposed", "evaluating"]),
            )
            .scalar()
        )

        info = {
            "decision_point": dp,
            "total_candidates": row.total,
            "pending_candidates": pending,
            "recent_promotion": recent_promotion is not None,
        }

        if recent_promotion:
            active.append(info)
        else:
            stalled.append(info)

    return {
        "stale_threshold_days": stale_days,
        "stalled_decision_points": stalled,
        "active_decision_points": active,
    }


def get_explore_exploit_balance(
    db: Session,
    tenant_id: uuid.UUID,
    days: int = 7,
) -> Dict[str, Any]:
    """Surface explore/exploit balance by decision point and platform."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    sql = text("""
        SELECT
            decision_point,
            action->>'platform' AS platform,
            action->>'routing_source' AS routing_source,
            COUNT(*) AS total,
            AVG(reward) FILTER (WHERE reward IS NOT NULL) AS avg_reward,
            COUNT(*) FILTER (WHERE reward IS NOT NULL) AS rated
        FROM rl_experiences
        WHERE tenant_id = CAST(:tid AS uuid)
          AND archived_at IS NULL
          AND created_at > :cutoff
        GROUP BY decision_point, action->>'platform', action->>'routing_source'
        ORDER BY decision_point, total DESC
    """)
    rows = db.execute(sql, {"tid": str(tenant_id), "cutoff": cutoff}).fetchall()

    by_decision_point = {}
    for row in rows:
        dp = row.decision_point or "unknown"
        if dp not in by_decision_point:
            by_decision_point[dp] = {
                "decision_point": dp,
                "total_experiences": 0,
                "exploration_count": 0,
                "exploitation_count": 0,
                "rollout_count": 0,
                "platforms": [],
            }

        entry = by_decision_point[dp]
        entry["total_experiences"] += row.total

        source = row.routing_source or "default"
        if "exploration" in source:
            entry["exploration_count"] += row.total
        elif "rollout" in source:
            entry["rollout_count"] += row.total
        else:
            entry["exploitation_count"] += row.total

        entry["platforms"].append({
            "platform": row.platform,
            "routing_source": source,
            "count": row.total,
            "avg_reward": round(float(row.avg_reward), 3) if row.avg_reward is not None else None,
            "rated": row.rated,
        })

    # Add explore/exploit ratio
    results = []
    for dp_info in by_decision_point.values():
        total = dp_info["total_experiences"]
        dp_info["explore_pct"] = round(dp_info["exploration_count"] / max(total, 1) * 100, 1)
        dp_info["exploit_pct"] = round(dp_info["exploitation_count"] / max(total, 1) * 100, 1)
        dp_info["rollout_pct"] = round(dp_info["rollout_count"] / max(total, 1) * 100, 1)
        results.append(dp_info)

    return {
        "period_days": days,
        "cutoff": cutoff.isoformat(),
        "decision_points": results,
    }


def get_rollout_status(
    db: Session,
    tenant_id: uuid.UUID,
) -> Dict[str, Any]:
    """Show all active and recent rollout experiments."""
    running = (
        db.query(LearningExperiment)
        .filter(
            LearningExperiment.tenant_id == tenant_id,
            LearningExperiment.status == "running",
            LearningExperiment.experiment_type == "split",
        )
        .all()
    )

    recent_completed = (
        db.query(LearningExperiment)
        .filter(
            LearningExperiment.tenant_id == tenant_id,
            LearningExperiment.status.in_(["completed", "aborted"]),
            LearningExperiment.experiment_type == "split",
        )
        .order_by(LearningExperiment.completed_at.desc())
        .limit(10)
        .all()
    )

    def _exp_summary(exp):
        return {
            "experiment_id": str(exp.id),
            "candidate_id": str(exp.candidate_id),
            "decision_point": exp.decision_point,
            "experiment_type": exp.experiment_type,
            "status": exp.status,
            "rollout_pct": exp.rollout_pct,
            "control": {"n": exp.control_sample_size, "avg_reward": exp.control_avg_reward},
            "treatment": {"n": exp.treatment_sample_size, "avg_reward": exp.treatment_avg_reward},
            "improvement_pct": exp.improvement_pct,
            "is_significant": exp.is_significant,
            "started_at": exp.started_at.isoformat() if exp.started_at else None,
            "completed_at": exp.completed_at.isoformat() if exp.completed_at else None,
        }

    return {
        "running_rollouts": [_exp_summary(e) for e in running],
        "recent_completed": [_exp_summary(e) for e in recent_completed],
    }
