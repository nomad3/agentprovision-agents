"""HCA Deal Intelligence tools.

LLM-powered tools for M&A deal sourcing, prospect discovery, scoring,
outreach generation, and pipeline management. Communicates with the
HCA API service and syncs data to the knowledge graph.
"""
import logging
from typing import Optional

import httpx

from services.knowledge_graph import get_knowledge_service
from tools.knowledge_tools import _resolve_tenant_id
from config.settings import settings

logger = logging.getLogger(__name__)

_hca_client: Optional[httpx.AsyncClient] = None


def _get_hca_client() -> httpx.AsyncClient:
    """Return a singleton httpx client for the HCA API."""
    global _hca_client
    if _hca_client is None:
        headers = {}
        if settings.hca_service_key:
            headers["Authorization"] = f"Bearer {settings.hca_service_key}"
        _hca_client = httpx.AsyncClient(
            base_url=settings.hca_api_url,
            timeout=60.0,
            headers=headers,
        )
    return _hca_client


async def discover_prospects(
    industry: str,
    revenue_min: Optional[float] = None,
    revenue_max: Optional[float] = None,
    geography: Optional[str] = None,
    max_results: int = 20,
    tenant_id: str = "auto",
) -> dict:
    """Discover M&A acquisition prospects matching the given criteria.

    Uses AI-driven sourcing to find companies that match the specified
    industry, revenue range, and geographic filters.

    Args:
        industry: Target industry vertical (e.g. "HVAC", "plumbing", "electrical").
        revenue_min: Minimum annual revenue in USD.
        revenue_max: Maximum annual revenue in USD.
        geography: Target geography (e.g. "Southeast US", "Texas").
        max_results: Maximum number of prospects to return.
        tenant_id: Tenant context.

    Returns:
        Dict with status and discovered prospects list.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        payload = {
            "industry": industry,
            "max_results": max_results,
            "tenant_id": tenant_id,
        }
        if revenue_min is not None:
            payload["revenue_min"] = revenue_min
        if revenue_max is not None:
            payload["revenue_max"] = revenue_max
        if geography is not None:
            payload["geography"] = geography

        resp = await client.post("/api/prospects/discover", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA discover_prospects HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA discover_prospects failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def save_discovered_prospects(
    prospects: list[dict],
    tenant_id: str = "auto",
) -> dict:
    """Save a batch of discovered prospects to the HCA database.

    Takes prospects returned by discover_prospects and persists them
    for pipeline tracking and further enrichment.

    Args:
        prospects: List of prospect dicts from discover_prospects.
        tenant_id: Tenant context.

    Returns:
        Dict with status and saved prospect IDs.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        payload = {
            "prospects": prospects,
            "tenant_id": tenant_id,
        }
        resp = await client.post("/api/prospects/discover/save", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA save_discovered_prospects HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA save_discovered_prospects failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def score_prospect(
    prospect_id: str,
    tenant_id: str = "auto",
) -> dict:
    """Score a prospect for acquisition fit using AI analysis.

    Evaluates the prospect on multiple dimensions including financial
    health, strategic fit, market position, and integration complexity.

    Args:
        prospect_id: UUID of the prospect to score.
        tenant_id: Tenant context.

    Returns:
        Dict with status and scoring breakdown.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        resp = await client.post(
            f"/api/prospects/{prospect_id}/score",
            json={"tenant_id": tenant_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA score_prospect HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA score_prospect failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def get_prospect_detail(
    prospect_id: str,
    tenant_id: str = "auto",
) -> dict:
    """Get full details for a specific prospect.

    Retrieves the complete prospect profile including company info,
    financials, scoring history, and outreach records.

    Args:
        prospect_id: UUID of the prospect.
        tenant_id: Tenant context.

    Returns:
        Dict with status and prospect detail.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        resp = await client.get(
            f"/api/prospects/{prospect_id}",
            params={"tenant_id": tenant_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA get_prospect_detail HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA get_prospect_detail failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def generate_research_brief(
    prospect_id: str,
    tenant_id: str = "auto",
) -> dict:
    """Generate an AI research brief for a prospect.

    Compiles market data, financial analysis, competitive landscape,
    and strategic rationale into a comprehensive brief.

    Args:
        prospect_id: UUID of the prospect to research.
        tenant_id: Tenant context.

    Returns:
        Dict with status and research brief content.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        resp = await client.post(
            f"/api/prospects/{prospect_id}/research",
            json={"tenant_id": tenant_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA generate_research_brief HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA generate_research_brief failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def generate_outreach(
    prospect_id: str,
    outreach_type: str = "email",
    tenant_id: str = "auto",
) -> dict:
    """Generate personalized outreach content for a prospect.

    Creates tailored messaging based on the prospect profile, deal
    thesis, and outreach type (email, letter, phone script).

    Args:
        prospect_id: UUID of the target prospect.
        outreach_type: Type of outreach - "email", "letter", or "phone_script".
        tenant_id: Tenant context.

    Returns:
        Dict with status and generated outreach draft.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        payload = {
            "prospect_id": prospect_id,
            "outreach_type": outreach_type,
            "tenant_id": tenant_id,
        }
        resp = await client.post("/api/outreach/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA generate_outreach HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA generate_outreach failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def get_outreach_drafts(
    prospect_id: str,
    tenant_id: str = "auto",
) -> dict:
    """Get all outreach drafts for a prospect.

    Retrieves previously generated outreach content including emails,
    letters, and phone scripts.

    Args:
        prospect_id: UUID of the prospect.
        tenant_id: Tenant context.

    Returns:
        Dict with status and list of outreach drafts.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        resp = await client.get(
            f"/api/outreach/prospect/{prospect_id}",
            params={"tenant_id": tenant_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA get_outreach_drafts HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA get_outreach_drafts failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def advance_pipeline_stage(
    prospect_id: str,
    new_stage: str,
    tenant_id: str = "auto",
) -> dict:
    """Advance a prospect to a new pipeline stage.

    Moves the prospect through the deal pipeline (e.g. identified ->
    contacted -> engaged -> loi -> due_diligence -> closed).

    Args:
        prospect_id: UUID of the prospect.
        new_stage: Target pipeline stage.
        tenant_id: Tenant context.

    Returns:
        Dict with status and updated prospect record.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        payload = {
            "new_stage": new_stage,
            "tenant_id": tenant_id,
        }
        resp = await client.put(
            f"/api/prospects/{prospect_id}/stage",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA advance_pipeline_stage HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA advance_pipeline_stage failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def list_prospects(
    stage: Optional[str] = None,
    industry: Optional[str] = None,
    score_min: Optional[float] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    tenant_id: str = "auto",
) -> dict:
    """List prospects with optional filters.

    Retrieves prospects from the HCA pipeline with filtering by stage,
    industry, minimum score, and free-text search.

    Args:
        stage: Filter by pipeline stage (e.g. "identified", "contacted").
        industry: Filter by industry vertical.
        score_min: Minimum acquisition fit score (0-100).
        search: Free-text search across prospect fields.
        sort: Sort field and direction (e.g. "score_desc", "created_at_desc").
        tenant_id: Tenant context.

    Returns:
        Dict with status and list of matching prospects.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    client = _get_hca_client()
    try:
        params = {"tenant_id": tenant_id}
        if stage is not None:
            params["stage"] = stage
        if industry is not None:
            params["industry"] = industry
        if score_min is not None:
            params["score_min"] = score_min
        if search is not None:
            params["search"] = search
        if sort is not None:
            params["sort"] = sort

        resp = await client.get("/api/prospects", params=params)
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "data": data}
    except httpx.HTTPStatusError as exc:
        logger.error("HCA list_prospects HTTP %s: %s", exc.response.status_code, exc.response.text)
        return {"status": "error", "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
    except Exception as exc:
        logger.error("HCA list_prospects failed: %s", exc)
        return {"status": "error", "error": str(exc)}


async def sync_prospect_to_knowledge_graph(
    prospect_id: str,
    tenant_id: str = "auto",
) -> dict:
    """Sync an HCA prospect into the knowledge graph.

    Fetches the full prospect from HCA and creates or updates the
    corresponding entity in the knowledge graph, enabling cross-system
    queries and relationship mapping.

    Args:
        prospect_id: UUID of the prospect to sync.
        tenant_id: Tenant context.

    Returns:
        Dict with status and the knowledge graph entity ID.
    """
    tenant_id = _resolve_tenant_id(tenant_id)

    # Fetch prospect detail from HCA
    detail_result = await get_prospect_detail(prospect_id, tenant_id=tenant_id)
    if detail_result.get("status") == "error":
        return detail_result

    prospect = detail_result.get("data", {})
    prospect_name = prospect.get("company_name") or prospect.get("name", f"Prospect {prospect_id}")

    kg = get_knowledge_service()

    # Check if entity already exists by searching for the prospect ID in properties
    existing = await kg.find_entities(
        query=prospect_name,
        tenant_id=tenant_id,
        entity_types=["prospect"],
        limit=5,
    )

    # Look for exact match by hca_prospect_id in properties
    matched_entity = None
    for entity in existing:
        props = entity.get("properties", {})
        if props.get("hca_prospect_id") == prospect_id:
            matched_entity = entity
            break

    properties = {
        "hca_prospect_id": prospect_id,
        "industry": prospect.get("industry"),
        "revenue": prospect.get("revenue"),
        "geography": prospect.get("geography"),
        "pipeline_stage": prospect.get("stage"),
        "score": prospect.get("score"),
        "source": "hca_deal_intelligence",
    }

    try:
        if matched_entity:
            # Update existing entity
            entity_id = matched_entity["id"]
            await kg.update_entity(
                entity_id=entity_id,
                updates={"properties": {**matched_entity.get("properties", {}), **properties}},
                reason="HCA prospect sync update",
            )
            return {
                "status": "success",
                "data": {
                    "entity_id": entity_id,
                    "action": "updated",
                    "prospect_name": prospect_name,
                },
            }
        else:
            # Create new entity
            entity = await kg.create_entity(
                name=prospect_name,
                entity_type="prospect",
                tenant_id=tenant_id,
                properties=properties,
                description=f"M&A prospect: {prospect_name} ({prospect.get('industry', 'unknown')} industry)",
                category="lead",
                confidence=0.9,
            )
            return {
                "status": "success",
                "data": {
                    "entity_id": entity.get("id"),
                    "action": "created",
                    "prospect_name": prospect_name,
                },
            }
    except Exception as exc:
        logger.error("HCA sync_prospect_to_knowledge_graph failed: %s", exc)
        return {"status": "error", "error": str(exc)}
