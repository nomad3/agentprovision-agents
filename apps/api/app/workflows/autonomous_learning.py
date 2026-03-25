"""Autonomous Learning Workflow — the nightly heartbeat.

Long-running workflow (one per tenant) that runs the self-improvement
pipeline: collect metrics → generate candidates → evaluate offline →
manage rollouts → morning report. Uses continue_as_new every cycle.

Queue: servicetsunami-orchestration
Workflow ID: autonomous-learning-{tenant_id}
"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Optional


@workflow.defn(sandboxed=False)
class AutonomousLearningWorkflow:
    """Nightly self-improvement cycle. One instance per tenant.

    Default cycle: every 24h at ~02:00 UTC.
    Activities:
      1. collect_learning_metrics
      2. generate_and_evaluate_candidates
      3. manage_active_rollouts
      4. generate_morning_report
    """

    @workflow.run
    async def run(
        self,
        tenant_id: str,
        cycle_interval_seconds: int = 86400,  # 24h default
        last_cycle_summary: Optional[str] = None,
    ) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=30),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=120),
        )
        activity_timeout = timedelta(minutes=5)

        workflow.logger.info(
            f"Autonomous learning cycle starting for tenant {tenant_id[:8]}"
        )

        cycle_result = {
            "tenant_id": tenant_id,
            "metrics": {},
            "candidates_generated": 0,
            "candidates_evaluated": 0,
            "rollouts_managed": 0,
            "report_sent": False,
            "errors": [],
        }

        # Step 1: Collect learning metrics
        try:
            metrics = await workflow.execute_activity(
                "collect_learning_metrics",
                args=[tenant_id],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
            cycle_result["metrics"] = metrics
        except Exception as e:
            workflow.logger.error(f"Step 1 (collect_learning_metrics) failed: {e}")
            cycle_result["errors"].append(f"collect_metrics: {e}")

        # Step 2: Generate and evaluate candidates
        try:
            eval_result = await workflow.execute_activity(
                "generate_and_evaluate_candidates",
                args=[tenant_id, cycle_result.get("metrics", {})],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
            cycle_result["candidates_generated"] = eval_result.get("generated", 0)
            cycle_result["candidates_evaluated"] = eval_result.get("evaluated", 0)
        except Exception as e:
            workflow.logger.error(f"Step 2 (generate_and_evaluate) failed: {e}")
            cycle_result["errors"].append(f"generate_evaluate: {e}")

        # Step 3: Manage active rollouts
        try:
            rollout_result = await workflow.execute_activity(
                "manage_active_rollouts",
                args=[tenant_id],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
            cycle_result["rollouts_managed"] = rollout_result.get("managed", 0)
        except Exception as e:
            workflow.logger.error(f"Step 3 (manage_rollouts) failed: {e}")
            cycle_result["errors"].append(f"manage_rollouts: {e}")

        # Step 4: Generate and send morning report
        try:
            report_result = await workflow.execute_activity(
                "generate_morning_report",
                args=[tenant_id, cycle_result],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
            cycle_result["report_sent"] = report_result.get("sent", False)
        except Exception as e:
            workflow.logger.error(f"Step 4 (morning_report) failed: {e}")
            cycle_result["errors"].append(f"morning_report: {e}")

        summary = (
            f"cycle complete: {cycle_result['candidates_generated']} generated, "
            f"{cycle_result['candidates_evaluated']} evaluated, "
            f"{cycle_result['rollouts_managed']} rollouts managed, "
            f"report={'sent' if cycle_result['report_sent'] else 'failed'}, "
            f"errors={len(cycle_result['errors'])}"
        )
        workflow.logger.info(f"Autonomous learning: {summary}")

        # Sleep until next cycle
        await workflow.sleep(timedelta(seconds=cycle_interval_seconds))
        workflow.continue_as_new(args=[
            tenant_id,
            cycle_interval_seconds,
            summary,
        ])
