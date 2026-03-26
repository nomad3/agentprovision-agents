"""Self-improvement activities — dispatch code tasks for the learning system to improve itself."""

import logging
import uuid
from datetime import timedelta
from typing import Optional

from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn(name="dispatch_self_improvement_task")
async def dispatch_self_improvement_task(
    tenant_id: str,
    task_description: str,
    context: Optional[str] = None,
) -> dict:
    """Dispatch a code task to the code-worker CLI to implement a self-improvement.

    The code-worker will:
    1. Create a feature branch
    2. Use Claude Code CLI to implement the change
    3. Commit, push, and open a PR
    4. GH Actions auto-deploys on merge to main

    This is how the learning system modifies its own code.
    """
    from temporalio.client import Client
    from app.core.config import settings

    try:
        client = await Client.connect(settings.TEMPORAL_ADDRESS)

        # The code-worker expects a CodeTaskInput dataclass, but Temporal
        # serializes it as a dict. We match the dataclass fields.
        task_input = {
            "task_description": task_description,
            "tenant_id": tenant_id,
            "context": context,
        }

        handle = await client.start_workflow(
            "CodeTaskWorkflow",
            task_input,
            id=f"self-improve-{uuid.uuid4().hex[:12]}",
            task_queue="servicetsunami-code",
            execution_timeout=timedelta(minutes=60),
        )

        logger.info(
            "Dispatched self-improvement task for tenant %s: %s (workflow=%s)",
            tenant_id[:8], task_description[:100], handle.id,
        )

        return {
            "dispatched": True,
            "workflow_id": handle.id,
            "task_description": task_description[:200],
        }
    except Exception as e:
        logger.error("Failed to dispatch self-improvement task: %s", e)
        return {
            "dispatched": False,
            "error": str(e),
        }


def build_skill_creation_task(gap_type: str, industry: str, description: str) -> str:
    """Build a code task description for creating a new MCP tool or skill."""
    return (
        f"## Self-Improvement: Create New Capability\n\n"
        f"The autonomous learning system detected a skill gap:\n"
        f"- **Gap type**: {gap_type}\n"
        f"- **Industry**: {industry}\n"
        f"- **Description**: {description}\n\n"
        f"### Task\n"
        f"Create a new skill or MCP tool to address this gap.\n\n"
        f"If it's a tool_missing gap:\n"
        f"- Add a new MCP tool function in `apps/mcp-server/src/mcp_tools/`\n"
        f"- Follow the existing tool patterns (use @mcp.tool() decorator)\n"
        f"- Register it in the __init__.py\n\n"
        f"If it's a knowledge_gap:\n"
        f"- Create a skill.md file in `apps/api/app/skills/<skill_name>/`\n"
        f"- The skill should contain prompting instructions for the agent\n\n"
        f"If it's a prompt_weakness:\n"
        f"- Improve the relevant agent's skill body or identity profile\n\n"
        f"### Constraints\n"
        f"- Create a new branch, commit, and open a PR\n"
        f"- Do NOT modify safety policies or trust thresholds\n"
        f"- Do NOT modify existing MCP tools (only add new ones)\n"
        f"- Keep changes minimal and focused on this specific gap\n"
        f"- Include a brief test or verification step\n"
    )


def build_config_optimization_task(decision_point: str, recommendation: str) -> str:
    """Build a code task for optimizing routing configuration."""
    return (
        f"## Self-Improvement: Optimize Routing Configuration\n\n"
        f"The autonomous learning system recommends a configuration change:\n"
        f"- **Decision point**: {decision_point}\n"
        f"- **Recommendation**: {recommendation}\n\n"
        f"### Task\n"
        f"Update the routing configuration to implement this recommendation.\n"
        f"This may involve:\n"
        f"- Updating the agent_router.py routing logic\n"
        f"- Modifying exploration rates in decision_point_config\n"
        f"- Adjusting default platform preferences\n\n"
        f"### Constraints\n"
        f"- Create a new branch, commit, and open a PR\n"
        f"- Do NOT disable the fallback chain\n"
        f"- Do NOT modify safety policies\n"
        f"- Keep changes minimal and reversible\n"
    )


def build_enhancement_task(title: str, description: str, files_to_modify: list) -> str:
    """Build a generic code enhancement task."""
    files_str = "\n".join(f"- `{f}`" for f in files_to_modify) if files_to_modify else "- Determine based on analysis"
    return (
        f"## Self-Improvement: {title}\n\n"
        f"{description}\n\n"
        f"### Files likely affected\n"
        f"{files_str}\n\n"
        f"### Constraints\n"
        f"- Create a new branch, commit, and open a PR\n"
        f"- Do NOT modify safety policies, trust thresholds, or identity profiles\n"
        f"- Keep changes minimal and focused\n"
        f"- Run py_compile on all modified files before committing\n"
    )
