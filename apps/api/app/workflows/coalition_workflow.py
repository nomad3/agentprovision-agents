"""CoalitionWorkflow — manages structured multi-agent collaboration via ChatCliWorkflow."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.coalition_activities import (
        select_coalition_template,
        initialize_collaboration,
        prepare_collaboration_step,
        record_collaboration_step,
        finalize_collaboration,
    )


@workflow.defn
class CoalitionWorkflow:
    @workflow.run
    async def run(self, tenant_id: str, chat_session_id: str = None, task_description: str = None) -> dict:
        # Support cross-pod dispatch pattern where arguments are passed as a single dict.
        # Round-2 review B1 (#440): also extract pattern + role_overrides from the
        # dict-unpack branch so `alpha coalition run --pattern X` is honored
        # end-to-end instead of being silently overridden by the keyword router
        # inside `select_coalition_template`.
        pattern: str | None = None
        role_overrides: dict | None = None
        if isinstance(tenant_id, dict) and chat_session_id is None:
            data = tenant_id
            tenant_id = data.get("tenant_id")
            chat_session_id = data.get("chat_session_id")
            task_description = data.get("task_description")
            pattern = data.get("pattern")
            role_overrides = data.get("role_overrides")

        retry = RetryPolicy(maximum_attempts=3)
        activity_timeout = timedelta(seconds=60)
        cli_timeout = timedelta(minutes=15)

        # 1. Select the best team shape for this task. When `pattern` is
        # explicit, the activity must skip its internal keyword router and
        # use the supplied value; `role_overrides` then layers caller-pinned
        # role→agent_slug mappings on top of the default role assignments.
        template = await workflow.execute_activity(
            select_coalition_template,
            args=[tenant_id, chat_session_id, task_description, pattern, role_overrides],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry,
        )

        # 2. Initialize Shared Blackboard and Collaboration Session
        # Pass task_description so it is stored verbatim as the blackboard title,
        # allowing prepare_collaboration_step to reconstruct the original prompt.
        session_info = await workflow.execute_activity(
            initialize_collaboration,
            args=[tenant_id, chat_session_id, template, task_description],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry,
        )

        collaboration_id = session_info["collaboration_id"]
        results = []

        # 3. Execute collaboration phases: prepare → ChatCliWorkflow → record
        for i in range(session_info["max_rounds"]):
            # 3a. Prepare: read blackboard, build step input dict
            step_input = await workflow.execute_activity(
                prepare_collaboration_step,
                args=[tenant_id, collaboration_id, i],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry,
            )

            # 3b. Execute: dispatch ChatCliWorkflow as child workflow on agentprovision-code queue.
            # workflow.execute_child_workflow() is deterministic — Temporal handles cross-queue routing
            # natively via task_queue without needing an external client connection.
            cli_result = await workflow.execute_child_workflow(
                "ChatCliWorkflow",
                args=[{
                    "platform": step_input["platform"],
                    "message": step_input["message"],
                    "tenant_id": tenant_id,
                    "instruction_md_content": step_input["instruction_md_content"],
                }],
                id=f"coalition-{collaboration_id}-step-{i}",
                task_queue="agentprovision-code",
                execution_timeout=cli_timeout,
            )
            # cli_result is deserialized by Temporal — normalize to dict
            if not isinstance(cli_result, dict):
                cli_result = {"response_text": str(cli_result), "success": True}

            # 3c. Record: write to blackboard + publish Redis events + async scoring
            response_text = (
                cli_result.get("response_text", "")
                if cli_result.get("success")
                else f"[CLI error: {cli_result.get('error', 'unknown')}]"
            )
            step_result = await workflow.execute_activity(
                record_collaboration_step,
                args=[
                    tenant_id,
                    collaboration_id,
                    response_text,
                    step_input["agent_slug"],
                    step_input["agent_role"],
                    step_input["current_phase"],
                ],
                start_to_close_timeout=activity_timeout,
                retry_policy=retry,
            )
            results.append(step_result)

            if step_result.get("consensus_reached"):
                break

        # 4. Finalize and report back to the chat session
        final_report = await workflow.execute_activity(
            finalize_collaboration,
            args=[tenant_id, collaboration_id],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry,
        )

        return {
            "status": "completed",
            "collaboration_id": collaboration_id,
            "final_report": final_report,
            "rounds": len(results),
        }
