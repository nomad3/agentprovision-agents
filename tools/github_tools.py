"""GitHub integration tools for self-modifying dev team agents.

Provides capabilities to manage branches, open pull requests, and check CI statuses
for GitOps-driven deployments and isolated microservice testing.
"""
import httpx
import logging
from typing import Optional

from config.settings import settings
from tools.shell_tools import execute_shell

logger = logging.getLogger(__name__)

def _get_github_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"token {settings.github_token}",
            "Accept": "application/vnd.github.v3+json",
        },
        timeout=30.0,
    )

async def create_branch(branch_name: str, working_dir: str = "/app") -> dict:
    """Creates a new branch locally and switches to it."""
    result = await execute_shell(f"git checkout -b {branch_name}", working_dir=working_dir)
    return {
        "status": "success" if result["return_code"] == 0 else "error",
        "detail": result["stderr"] or result["stdout"]
    }

async def commit_and_push(branch_name: str, commit_message: str, files: Optional[list[str]] = None, working_dir: str = "/app") -> dict:
    """Stages, commits, and pushes changes to the specified branch."""
    if files:
        for f in files:
            await execute_shell(f"git add {f}", working_dir=working_dir)
    else:
        await execute_shell("git add -A", working_dir=working_dir)
    
    safe_message = commit_message.replace("'", "'\\''")
    await execute_shell(f"git commit -m '{safe_message}'", working_dir=working_dir)
    result = await execute_shell(f"git push -u origin {branch_name}", working_dir=working_dir)
    
    return {
        "status": "success" if result["return_code"] == 0 else "error",
        "detail": result["stderr"] or result["stdout"]
    }

async def create_pull_request(title: str, body: str, head_branch: str, base_branch: str = "main") -> dict:
    """Opens a Pull Request via GitHub API."""
    if not settings.github_token:
        return {"status": "error", "detail": "github_token not configured."}
        
    async with _get_github_client() as client:
        response = await client.post(
            f"/repos/{settings.github_repository}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch
            }
        )
        if response.status_code == 201:
            data = response.json()
            return {"status": "success", "pr_url": data.get("html_url"), "pr_number": data.get("number")}
        else:
            return {"status": "error", "detail": response.text}

async def check_pr_status(pr_number: int) -> dict:
    """Checks the CI/CD status of a specific Pull Request via GitHub API."""
    if not settings.github_token:
        return {"status": "error", "detail": "github_token not configured."}
        
    async with _get_github_client() as client:
        pr_response = await client.get(f"/repos/{settings.github_repository}/pulls/{pr_number}")
        if pr_response.status_code != 200:
            return {"status": "error", "detail": "Could not fetch PR details."}
            
        sha = pr_response.json()["head"]["sha"]
        
        checks_response = await client.get(f"/repos/{settings.github_repository}/commits/{sha}/check-runs")
        if checks_response.status_code == 200:
            return {"status": "success", "checks": checks_response.json().get("check_runs", [])}
        else:
            return {"status": "error", "detail": checks_response.text}
