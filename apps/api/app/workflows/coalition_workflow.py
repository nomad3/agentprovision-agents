"""CoalitionWorkflow — manages structured multi-agent collaboration.

Implements the STP (ServiceTsunami Protocol) orchestration for team-based
task execution. Dispatched by the Supervisor (Luna) when a complex task
requires specialized agents (e.g., Coder + Critic).
"""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.coalition_activities import (
        select_coalition_template,
        initialize_collaboration,
        execute_collaboration_step,
        finalize_collaboration,
    )


@workflow.defn
class CoalitionWorkflow:
    @workflow.run
    async def run(self, tenant_id: str, chat_session_id: str, task_description: str) -> dict:
        retry = RetryPolicy(maximum_attempts=3)
        timeout = timedelta(seconds=300)

        # 1. Select the best team shape (template) for this task
        template = await workflow.execute_activity(
            select_coalition_template,
            args=[tenant_id, chat_session_id, task_description],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry,
        )

        # 2. Initialize the Shared Blackboard and Collaboration Session
        session_info = await workflow.execute_activity(
            initialize_collaboration,
            args=[tenant_id, chat_session_id, template],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry,
        )

        # 3. Execute the collaboration pattern (e.g., Propose-Critique-Revise)
        # For Phase 1, we run up to max_rounds or until consensus.
        collaboration_id = session_info["collaboration_id"]
        results = []
        for i in range(session_info["max_rounds"]):
            step_result = await workflow.execute_activity(
                execute_collaboration_step,
                args=[tenant_id, collaboration_id, i],
                start_to_close_timeout=timeout,
                retry_policy=retry,
            )
            results.append(step_result)
            if step_result.get("consensus_reached"):
                break

        # 4. Finalize and report back to the main chat session
        final_report = await workflow.execute_activity(
            finalize_collaboration,
            args=[tenant_id, collaboration_id],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=retry,
        )

        return {
            "status": "completed",
            "collaboration_id": collaboration_id,
            "final_report": final_report,
            "rounds": len(results),
        }
