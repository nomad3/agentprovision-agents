"""Feedback, self-diagnosis, and regression-monitoring activities for the nightly learning cycle."""

import logging
import uuid
from datetime import datetime, timedelta

from temporalio import activity

logger = logging.getLogger(__name__)

# Keywords that indicate positive/negative feedback
_POSITIVE_KEYWORDS = ["good call", "approve", "great", "looks good", "sounds right", "go ahead", "try it"]
_NEGATIVE_KEYWORDS = ["bad idea", "don't route", "reject", "no", "stop", "revert", "rollback", "bad", "wrong"]
_DIRECTION_KEYWORDS = ["try", "consider", "maybe", "what about", "how about", "suggest"]
_CORRECTION_KEYWORDS = ["actually", "correction", "wrong", "incorrect", "fix this", "should be"]

# Keywords that indicate the message references a learning report
_REPORT_KEYWORDS = ["learning report", "morning report", "nightly report", "your report", "the report"]


@activity.defn(name="process_human_feedback")
async def process_human_feedback(tenant_id: str) -> dict:
    """Scan recent chat messages for human feedback on learning reports."""
    from app.db.session import SessionLocal
    from app.models.feedback_record import FeedbackRecord
    from sqlalchemy import text

    db = SessionLocal()
    try:
        tenant_uuid = uuid.UUID(tenant_id)
        since = datetime.utcnow() - timedelta(hours=24)

        # Look for recent messages that mention learning reports
        messages = db.execute(text("""
            SELECT id, content, created_at, session_id
            FROM chat_messages
            WHERE tenant_id = CAST(:tid AS uuid)
              AND created_at > :since
              AND role = 'user'
              AND (
                LOWER(content) LIKE '%learning report%'
                OR LOWER(content) LIKE '%morning report%'
                OR LOWER(content) LIKE '%nightly report%'
                OR LOWER(content) LIKE '%your report%'
              )
            ORDER BY created_at DESC
            LIMIT 20
        """), {"tid": tenant_id, "since": since}).fetchall()

        processed = 0
        for msg in messages:
            content_lower = msg.content.lower()

            # Determine feedback type
            feedback_type, parsed_intent = _classify_feedback(content_lower)
            if not feedback_type:
                continue

            # Avoid duplicate processing
            already_exists = db.execute(text("""
                SELECT 1 FROM feedback_records
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND report_id = :rid
                  AND content = :content
                LIMIT 1
            """), {
                "tid": tenant_id,
                "rid": str(msg.session_id),
                "content": msg.content[:500],
            }).fetchone()

            if already_exists:
                continue

            record = FeedbackRecord(
                tenant_id=tenant_uuid,
                report_id=str(msg.session_id),
                feedback_type=feedback_type,
                content=msg.content[:1000],
                parsed_intent=parsed_intent,
                applied=False,
            )
            db.add(record)
            processed += 1

        db.commit()

        logger.info(
            "Processed %d feedback records for tenant %s",
            processed, tenant_id[:8],
        )
        return {"feedback_processed": processed}
    except Exception as e:
        logger.error("process_human_feedback failed for %s: %s", tenant_id[:8], e)
        raise
    finally:
        db.close()


@activity.defn(name="run_self_diagnosis")
async def run_self_diagnosis(tenant_id: str) -> dict:
    """Aggregate simulation failures and compute an overall platform health signal."""
    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        today = datetime.utcnow().date()

        # Simulation failure summary from the latest cycle
        failure_rows = db.execute(text("""
            SELECT
                sr.failure_type,
                COUNT(*) AS cnt,
                AVG(sr.quality_score) AS avg_score
            FROM simulation_results sr
            JOIN simulation_scenarios ss ON ss.id = sr.scenario_id
            WHERE sr.tenant_id = CAST(:tid AS uuid)
              AND ss.cycle_date = :today
              AND sr.is_simulation = TRUE
              AND sr.failure_type IS NOT NULL
            GROUP BY sr.failure_type
            ORDER BY cnt DESC
        """), {"tid": tenant_id, "today": today}).fetchall()

        top_failures = [
            {
                "failure_type": r.failure_type,
                "count": r.cnt,
                "avg_score": round(float(r.avg_score), 2) if r.avg_score else 0,
            }
            for r in failure_rows
        ]

        # Active skill gaps count
        skill_gaps_active = db.execute(text("""
            SELECT COUNT(*) FROM skill_gaps
            WHERE tenant_id = CAST(:tid AS uuid)
              AND status IN ('detected', 'acknowledged', 'in_progress')
        """), {"tid": tenant_id}).scalar() or 0

        # Total simulations run today
        total_simulations = db.execute(text("""
            SELECT COUNT(*) FROM simulation_results sr
            JOIN simulation_scenarios ss ON ss.id = sr.scenario_id
            WHERE sr.tenant_id = CAST(:tid AS uuid)
              AND ss.cycle_date = :today
              AND sr.is_simulation = TRUE
        """), {"tid": tenant_id, "today": today}).scalar() or 0

        # Failure rate
        total_failures = sum(r["count"] for r in top_failures)
        failure_rate = (total_failures / total_simulations) if total_simulations > 0 else 0.0

        # Overall health classification
        if failure_rate < 0.2 and skill_gaps_active < 3:
            overall_health = "good"
        elif failure_rate < 0.4 and skill_gaps_active < 7:
            overall_health = "needs_attention"
        else:
            overall_health = "critical"

        diagnosis = {
            "top_failures": top_failures[:5],
            "skill_gaps_active": skill_gaps_active,
            "total_simulations": total_simulations,
            "total_failures": total_failures,
            "failure_rate": round(failure_rate, 3),
            "overall_health": overall_health,
        }

        logger.info(
            "Self-diagnosis for tenant %s: health=%s, failure_rate=%.2f, gaps=%d",
            tenant_id[:8], overall_health, failure_rate, skill_gaps_active,
        )
        return diagnosis
    except Exception as e:
        logger.error("run_self_diagnosis failed for %s: %s", tenant_id[:8], e)
        raise
    finally:
        db.close()


@activity.defn(name="monitor_regression")
async def monitor_regression(tenant_id: str) -> dict:
    """Check promoted policy candidates for regression vs their baseline reward."""
    from app.db.session import SessionLocal
    from app.models.learning_experiment import PolicyCandidate
    from app.models.notification import Notification
    from sqlalchemy import text

    db = SessionLocal()
    try:
        tenant_uuid = uuid.UUID(tenant_id)
        now = datetime.utcnow()
        last_24h = now - timedelta(hours=24)

        # Get all promoted candidates with a baseline_reward stored in evidence
        promoted = (
            db.query(PolicyCandidate)
            .filter(
                PolicyCandidate.tenant_id == tenant_uuid,
                PolicyCandidate.status == "promoted",
            )
            .all()
        )

        regressions_detected = 0
        candidates_checked = len(promoted)

        for candidate in promoted:
            evidence = candidate.evidence or {}
            baseline_reward = evidence.get("baseline_reward")
            if baseline_reward is None:
                continue

            try:
                baseline_reward = float(baseline_reward)
            except (TypeError, ValueError):
                continue

            # Compute rolling 24h avg reward for RL experiences attributed to this candidate's routing
            decision_point = candidate.decision_point
            rolling_avg = db.execute(text("""
                SELECT AVG(reward) AS avg_reward, COUNT(*) AS n
                FROM rl_experiences
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND decision_point = :dp
                  AND action->>'routing_source' = 'rl_policy'
                  AND created_at > :since
                  AND reward IS NOT NULL
                  AND archived_at IS NULL
            """), {
                "tid": tenant_id,
                "dp": decision_point,
                "since": last_24h,
            }).one()

            if not rolling_avg.avg_reward or rolling_avg.n < 5:
                # Not enough data to detect regression
                continue

            current_avg = float(rolling_avg.avg_reward)
            regression_pct = (baseline_reward - current_avg) / baseline_reward * 100 if baseline_reward > 0 else 0

            if regression_pct > 10.0:
                # Regression detected — demote candidate and notify
                logger.warning(
                    "Regression detected for candidate %s (tenant %s): "
                    "baseline=%.3f, current=%.3f, regression=%.1f%%",
                    str(candidate.id)[:8], tenant_id[:8],
                    baseline_reward, current_avg, regression_pct,
                )

                candidate.status = "evaluating"
                evidence["regression_detected_at"] = now.isoformat()
                evidence["regression_pct"] = round(regression_pct, 2)
                evidence["regression_current_avg"] = round(current_avg, 3)
                candidate.evidence = evidence

                # Create regression notification
                notification = Notification(
                    tenant_id=tenant_id,
                    source="autonomous_learning",
                    title=f"Regression Detected — {decision_point} policy reverted",
                    body=(
                        f"Policy candidate for '{decision_point}' showed {regression_pct:.1f}% regression "
                        f"vs baseline (current avg: {current_avg:.3f}, baseline: {baseline_reward:.3f}). "
                        f"Candidate has been reverted to evaluating state."
                    ),
                    priority="high",
                    reference_id=f"regression:{candidate.id}",
                    reference_type="learning_regression",
                )
                db.add(notification)
                regressions_detected += 1

        db.commit()

        logger.info(
            "Regression monitor for tenant %s: checked=%d, regressions=%d",
            tenant_id[:8], candidates_checked, regressions_detected,
        )
        return {
            "regressions_detected": regressions_detected,
            "candidates_checked": candidates_checked,
        }
    except Exception as e:
        logger.error("monitor_regression failed for %s: %s", tenant_id[:8], e)
        raise
    finally:
        db.close()


# --- Private helpers ---

def _classify_feedback(content_lower: str) -> tuple:
    """Return (feedback_type, parsed_intent) based on message content."""
    if any(kw in content_lower for kw in _POSITIVE_KEYWORDS):
        if "routing" in content_lower or "platform" in content_lower:
            return ("approval", "approve_routing_change")
        return ("approval", "general_approval")

    if any(kw in content_lower for kw in _NEGATIVE_KEYWORDS):
        if "routing" in content_lower or "platform" in content_lower:
            return ("rejection", "reject_platform")
        if "rollback" in content_lower or "revert" in content_lower:
            return ("rejection", "request_rollback")
        return ("rejection", "general_rejection")

    if any(kw in content_lower for kw in _CORRECTION_KEYWORDS):
        return ("correction", "factual_correction")

    if any(kw in content_lower for kw in _DIRECTION_KEYWORDS):
        return ("direction", "exploration_direction")

    return (None, None)
