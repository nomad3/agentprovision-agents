"""Gap 1: Daily journal synthesis workflow — auto-creates journals from conversations."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="Gap1JournalSynthesis")
class Gap1JournalSynthesis:
    """
    Long-running workflow that synthesizes daily journals from conversation history.

    Uses continue_as_new to run indefinitely with daily recurrence.
    Triggered by scheduler for each tenant.

    Runs every 24 hours (e.g., 8am local time) to capture the previous day's
    conversations and synthesize them into a SessionJournal entry.
    """

    @workflow.run
    async def run(self, tenant_id: str) -> None:
        """Run journal synthesis, then schedule next iteration."""
        from app.workflows.activities.journal_synthesis import (
            synthesize_daily_journal,
            synthesize_weekly_journal,
        )

        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2,
            maximum_attempts=3,
        )

        # Run daily journal synthesis
        try:
            await workflow.execute_activity(
                synthesize_daily_journal,
                tenant_id,
                retry_policy=retry_policy,
                start_to_close_timeout=timedelta(minutes=10),
            )
        except Exception as e:
            # Log but don't fail — continue to weekly synthesis
            workflow.logger.warning(f"Daily journal synthesis failed: {e}")

        # Run weekly journal on Sundays
        from datetime import datetime
        if datetime.utcnow().weekday() == 6:  # Sunday
            try:
                await workflow.execute_activity(
                    synthesize_weekly_journal,
                    tenant_id,
                    retry_policy=retry_policy,
                    start_to_close_timeout=timedelta(minutes=15),
                )
            except Exception as e:
                workflow.logger.warning(f"Weekly journal synthesis failed: {e}")

        # Schedule next run in 24 hours via continue_as_new
        await workflow.continue_as_new(tenant_id)
