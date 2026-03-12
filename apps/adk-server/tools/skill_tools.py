"""Bridge tools for executing file-based skills via the API."""

import json
import logging

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

API_BASE = settings.api_base_url.rstrip("/")
MCP_API_KEY = settings.mcp_api_key


async def list_skills(tenant_id: str = "auto") -> dict:
    """List all available file-based skills from the platform.

    Args:
        tenant_id: Tenant ID (auto-resolved).

    Returns:
        dict with a list of available skills, each with name, description, and required inputs.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{API_BASE}/api/v1/skills/library/internal",
            headers={"X-Internal-Key": MCP_API_KEY},
        )
        if resp.status_code != 200:
            return {"error": f"Failed to list skills: HTTP {resp.status_code}", "detail": resp.text[:500]}
        skills = resp.json()
        return {
            "skills": [
                {
                    "name": s.get("name"),
                    "description": s.get("description"),
                    "inputs": s.get("inputs", []),
                }
                for s in skills
            ]
        }


async def run_skill(skill_name: str, inputs: str, tenant_id: str = "auto") -> dict:
    """Execute a file-based skill by name with the given JSON inputs.

    Args:
        skill_name: The exact name of the skill to run (e.g. "Scrape Competitor SEO").
        inputs: JSON string of input parameters (e.g. '{"url": "https://example.com"}').
        tenant_id: Tenant ID (auto-resolved).

    Returns:
        dict with the skill execution result or error.
    """
    try:
        input_data = json.loads(inputs)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON inputs: {inputs}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{API_BASE}/api/v1/skills/library/internal/execute",
            headers={"X-Internal-Key": MCP_API_KEY},
            json={"skill_name": skill_name, "inputs": input_data},
        )
        if resp.status_code != 200:
            return {"error": f"Skill execution failed: HTTP {resp.status_code}", "detail": resp.text[:500]}
        return resp.json()


async def match_skills_to_context(user_message: str, tenant_id: str = "auto") -> dict:
    """Find skills that semantically match a user's message.
    Use this to check if there's a relevant skill before responding.
    Returns matched skills with similarity scores.

    Args:
        user_message: The user's message to match against skill descriptions.
        tenant_id: Tenant ID (auto-resolved).
    """
    try:
        params = {"q": user_message, "limit": 3}
        if tenant_id and tenant_id != "auto":
            params["tenant_id"] = tenant_id
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{API_BASE}/api/v1/skills/library/match",
                params=params,
                headers={"X-Internal-Key": MCP_API_KEY},
            )
            if resp.status_code == 200:
                return resp.json()
            return {"matches": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.warning("Skill match failed: %s", e)
        return {"matches": []}


async def recall_memory(
    query: str, tenant_id: str = "auto", types: str = "", limit: int = 10
) -> dict:
    """Semantic search across all memory — entities, activities, past conversations.
    Use this to recall relevant context about the user, their business, or past interactions.

    Args:
        query: What to search for in memory.
        tenant_id: Tenant ID (auto-resolved).
        types: Comma-separated content types to filter (entity, memory_activity, skill, chat_message). Empty = all.
        limit: Max results to return.
    """
    try:
        params: dict = {"q": query, "limit": limit}
        if types:
            params["types"] = types
        if tenant_id and tenant_id != "auto":
            params["tenant_id"] = tenant_id
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{API_BASE}/api/v1/memories/search/internal",
                params=params,
                headers={"X-Internal-Key": MCP_API_KEY},
            )
            if resp.status_code == 200:
                return resp.json()
            return {"results": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.warning("Memory recall failed: %s", e)
        return {"results": []}
