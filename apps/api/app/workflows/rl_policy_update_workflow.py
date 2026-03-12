from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities.rl_policy_update import (
        collect_tenant_experiences,
        update_tenant_policy,
        anonymize_and_aggregate_global,
        archive_old_experiences,
    )
    from app.services.rl_experience_service import DECISION_POINTS


@workflow.defn
class RLPolicyUpdateWorkflow:
    """Nightly batch workflow: collect -> update per-tenant -> anonymize for global -> archive."""

    @workflow.run
    async def run(self, tenant_id: str) -> dict:
        # Step 1: Collect experience stats
        stats = await workflow.execute_activity(
            collect_tenant_experiences, args=[tenant_id],
            start_to_close_timeout=timedelta(minutes=5),
        )

        # Step 2: Update tenant policy for each decision point with data
        updated = []
        for dp, dp_stats in stats.get("decision_points", {}).items():
            if dp_stats.get("count", 0) > 0:
                result = await workflow.execute_activity(
                    update_tenant_policy, args=[tenant_id, dp],
                    start_to_close_timeout=timedelta(minutes=5),
                )
                updated.append(result)

        # Step 3: Anonymize and aggregate into global baseline
        for dp in DECISION_POINTS:
            await workflow.execute_activity(
                anonymize_and_aggregate_global, args=[dp],
                start_to_close_timeout=timedelta(minutes=10),
            )

        # Step 4: Archive old experiences
        archive_result = await workflow.execute_activity(
            archive_old_experiences, args=[tenant_id, 90],
            start_to_close_timeout=timedelta(minutes=5),
        )

        return {
            "tenant_id": tenant_id,
            "policies_updated": len(updated),
            "archived": archive_result.get("archived", 0),
        }
