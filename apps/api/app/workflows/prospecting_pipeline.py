"""
Temporal workflow for prospecting pipeline orchestration.

Steps:
1. prospect_research - Enrichment and research on prospect entities
2. prospect_score - Score prospects via skills service (lead scoring)
3. prospect_qualify - BANT qualification filtering
4. prospect_outreach - Draft personalised outreach messages
5. prospect_notify - Create notification summary for the tenant
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List

from temporalio import activity, workflow

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Workflow input
# ---------------------------------------------------------------------------


@dataclass
class ProspectingPipelineInput:
    tenant_id: str
    entity_ids: List[str]
    params: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@workflow.defn(sandboxed=False)
class ProspectingPipelineWorkflow:
    """Durable 5-step prospecting pipeline.

    Steps:
    1. prospect_research  - Enrich prospect entities with external data
    2. prospect_score     - Score each prospect via lead-scoring skill
    3. prospect_qualify   - Apply BANT qualification filter
    4. prospect_outreach  - Draft personalised outreach messages
    5. prospect_notify    - Create a notification summary
    """

    @workflow.run
    async def run(self, input: ProspectingPipelineInput) -> Dict[str, Any]:
        tenant_id = input.tenant_id
        entity_ids = input.entity_ids
        params = input.params

        rubric_id = params.get("rubric_id")
        threshold = params.get("threshold", 70)
        template = params.get("template", "default")

        retry_policy = workflow.RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )

        workflow.logger.info(
            f"Starting prospecting pipeline for {len(entity_ids)} entities"
        )

        if not entity_ids:
            return {"status": "completed", "message": "No entities provided"}

        # Step 1: Research / Enrichment
        research_result = await workflow.execute_activity(
            "prospect_research",
            args=[tenant_id, entity_ids, params],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )
        if research_result.get("status") == "failed":
            return {"status": "error", "step": "research", "error": research_result.get("error")}

        # Step 2: Score
        score_result = await workflow.execute_activity(
            "prospect_score",
            args=[tenant_id, entity_ids, rubric_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )
        if score_result.get("status") == "failed":
            return {"status": "error", "step": "score", "error": score_result.get("error")}

        # Step 3: Qualify
        qualify_result = await workflow.execute_activity(
            "prospect_qualify",
            args=[tenant_id, entity_ids, threshold],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )
        qualified_ids = qualify_result.get("entity_ids", entity_ids)

        # Step 4: Outreach
        outreach_result = await workflow.execute_activity(
            "prospect_outreach",
            args=[tenant_id, qualified_ids, template],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Step 5: Notify
        results = {
            "total_entities": len(entity_ids),
            "qualified": len(qualified_ids),
            "outreach_generated": outreach_result.get("count", 0),
        }
        notify_result = await workflow.execute_activity(
            "prospect_notify",
            args=[tenant_id, results],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        return {
            "status": "completed",
            "total_entities": len(entity_ids),
            "qualified": len(qualified_ids),
            "outreach_generated": outreach_result.get("count", 0),
            "notification_id": notify_result.get("notification_id"),
        }


# ---------------------------------------------------------------------------
# Activity stubs
# ---------------------------------------------------------------------------


@activity.defn
async def prospect_research(
    tenant_id: str, entity_ids: List[str], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Enrich prospect entities with external data sources."""
    activity.logger.info(
        f"prospect_research: tenant={tenant_id} entities={len(entity_ids)}"
    )
    # Stub: will call enrichment services later
    return {"status": "completed", "entity_ids": entity_ids}


@activity.defn
async def prospect_score(
    tenant_id: str, entity_ids: List[str], rubric_id: str | None
) -> Dict[str, Any]:
    """Score prospects via the lead-scoring skill."""
    activity.logger.info(
        f"prospect_score: tenant={tenant_id} entities={len(entity_ids)} rubric={rubric_id}"
    )
    # Stub: will call skills.execute_skill with scoring skill
    return {"status": "completed", "entity_ids": entity_ids}


@activity.defn
async def prospect_qualify(
    tenant_id: str, entity_ids: List[str], threshold: int
) -> Dict[str, Any]:
    """Apply BANT qualification filter to scored prospects."""
    activity.logger.info(
        f"prospect_qualify: tenant={tenant_id} entities={len(entity_ids)} threshold={threshold}"
    )
    # Stub: will filter entities by score >= threshold
    return {"status": "completed", "entity_ids": entity_ids}


@activity.defn
async def prospect_outreach(
    tenant_id: str, entity_ids: List[str], template: str
) -> Dict[str, Any]:
    """Draft personalised outreach messages for qualified prospects."""
    activity.logger.info(
        f"prospect_outreach: tenant={tenant_id} entities={len(entity_ids)} template={template}"
    )
    # Stub: will generate outreach via LLM
    return {"status": "completed", "entity_ids": entity_ids, "count": len(entity_ids)}


@activity.defn
async def prospect_notify(
    tenant_id: str, results: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a notification summary for the prospecting pipeline run."""
    activity.logger.info(
        f"prospect_notify: tenant={tenant_id} results={results}"
    )
    # Stub: will create notification via notification service
    return {"status": "completed", "notification_id": None}
