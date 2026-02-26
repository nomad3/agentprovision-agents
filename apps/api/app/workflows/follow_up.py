"""
Temporal workflow for scheduled sales follow-up actions.

Waits for a configurable delay then executes a follow-up action
(send message, update pipeline stage, or create reminder).
"""
from temporalio import workflow
from datetime import timedelta
from dataclasses import dataclass


@dataclass
class FollowUpInput:
    entity_id: str
    tenant_id: str
    action: str  # "send_whatsapp", "update_stage", "remind"
    delay_hours: int
    message: str = ""


@workflow.defn(sandboxed=False)
class FollowUpWorkflow:
    """Delayed follow-up action for sales pipeline."""

    @workflow.run
    async def run(self, input: FollowUpInput) -> dict:
        workflow.logger.info(
            f"FollowUp scheduled: {input.action} for entity {input.entity_id} "
            f"in {input.delay_hours}h"
        )

        # Wait for the scheduled delay
        await workflow.sleep(timedelta(hours=input.delay_hours))

        # Execute the follow-up action
        result = await workflow.execute_activity(
            "execute_followup_action",
            args=[input],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=workflow.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
        )

        return result
