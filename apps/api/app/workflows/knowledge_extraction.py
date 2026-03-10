"""
Temporal workflow for knowledge extraction
"""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any

# Import activity definition
with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.knowledge_extraction import extract_knowledge_from_session

@workflow.defn
class KnowledgeExtractionWorkflow:
    @workflow.run
    async def run(self, session_id: str, tenant_id: str) -> Dict[str, Any]:
        workflow.logger.info(f"Starting knowledge extraction workflow for session {session_id}")

        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=60),
        )

        try:
            # Execute activity
            result = await workflow.execute_activity(
                extract_knowledge_from_session,
                args=[session_id, tenant_id],
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Knowledge extraction completed: {result}")
            return result
        except Exception as e:
            workflow.logger.error(
                f"Knowledge extraction failed for session {session_id} "
                f"after retries: {e}"
            )
            return {
                "status": "failed",
                "session_id": session_id,
                "tenant_id": tenant_id,
                "error": str(e),
            }
