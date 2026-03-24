"""Temporal workflow for periodic goal and commitment review.

Long-running workflow (one per tenant) that periodically reviews goals
and commitments: detects stalled, blocked, or overdue items, flags
contradictory states, and creates notifications for agents/users.

Uses continue_as_new to prevent history growth.
"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Optional


@workflow.defn(sandboxed=False)
class GoalReviewWorkflow:
    """Periodic goal and commitment review. One instance per tenant.

    Runs every N seconds (default 6h):
    review goals → detect stalled → check overdue commitments →
    flag contradictions → create notifications → sleep → continue_as_new

    Workflow ID: goal-review-{tenant_id}
    """

    @workflow.run
    async def run(
        self,
        tenant_id: str,
        review_interval_seconds: int = 21600,  # 6 hours default
        last_review_summary: Optional[str] = None,
    ) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=30),
        )
        activity_timeout = timedelta(minutes=2)

        workflow.logger.info(f"Goal review cycle for tenant {tenant_id[:8]}")

        review_result = {}
        step_errors = []

        # Step 1: Review goals — find stalled, blocked, contradictory
        try:
            review_result = await workflow.execute_activity(
                "review_goals",
                args=[tenant_id],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Step 1 (review_goals) failed: {e}")
            step_errors.append(f"review_goals: {e}")

        # Step 2: Check overdue commitments
        overdue_result = {}
        try:
            overdue_result = await workflow.execute_activity(
                "review_commitments",
                args=[tenant_id],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Step 2 (review_commitments) failed: {e}")
            step_errors.append(f"review_commitments: {e}")

        # Step 3: Create notifications for flagged items
        notifications_created = 0
        try:
            notifications_created = await workflow.execute_activity(
                "create_review_notifications",
                args=[tenant_id, review_result, overdue_result],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Step 3 (create_review_notifications) failed: {e}")
            step_errors.append(f"create_review_notifications: {e}")

        new_summary = (
            f"goals_reviewed={review_result.get('total_reviewed', 0)}, "
            f"stalled={review_result.get('stalled_count', 0)}, "
            f"overdue_commitments={overdue_result.get('overdue_count', 0)}, "
            f"notifications={notifications_created}"
        )
        workflow.logger.info(f"Goal review complete: {new_summary}")

        # Sleep until next cycle
        await workflow.sleep(timedelta(seconds=review_interval_seconds))
        workflow.continue_as_new(args=[
            tenant_id,
            review_interval_seconds,
            new_summary,
        ])
