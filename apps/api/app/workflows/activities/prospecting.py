"""
Prospecting pipeline activity stubs.

Extracted from the former static ProspectingPipelineWorkflow so
DynamicWorkflowExecutor can dispatch them as Temporal activities.
"""

from typing import Any, Dict, List

from temporalio import activity

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
