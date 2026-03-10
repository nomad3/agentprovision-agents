from datetime import timedelta
from typing import Dict, Any
from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activity definition
with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.agent_kit_execution import execute_agent_kit_activity

@workflow.defn
class AgentKitExecutionWorkflow:
    @workflow.run
    async def run(self, agent_kit_id: str, tenant_id: str, input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        workflow.logger.info(f"AgentKitExecutionWorkflow started for kit {agent_kit_id}")

        try:
            # Execute the activity
            result = await workflow.execute_activity(
                execute_agent_kit_activity,
                args=[agent_kit_id, tenant_id, input_data],
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
        except Exception as e:
            workflow.logger.error(
                f"AgentKitExecutionWorkflow failed for kit {agent_kit_id}, "
                f"tenant {tenant_id}: {e}"
            )
            return {
                "status": "error",
                "agent_kit_id": agent_kit_id,
                "tenant_id": tenant_id,
                "error": str(e),
            }

        workflow.logger.info(f"AgentKitExecutionWorkflow completed with result: {result}")
        return result
