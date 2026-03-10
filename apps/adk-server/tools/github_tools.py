"""GitHub tools for agent orchestration.

Uses stored OAuth token from the credential vault to call GitHub REST API
on behalf of the authenticated tenant.
"""
import logging
from typing import Optional

import httpx

from config.settings import settings
from tools.knowledge_tools import _resolve_tenant_id

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

_api_client: Optional[httpx.AsyncClient] = None


def _get_api_client() -> httpx.AsyncClient:
    global _api_client
    if _api_client is None:
        _api_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=30.0,
        )
    return _api_client


async def _get_github_token(tenant_id: str) -> Optional[str]:
    """Retrieve GitHub OAuth token from the vault."""
    client = _get_api_client()
    try:
        resp = await client.get(
            "/api/v1/oauth/internal/token/github",
            headers={"X-Internal-Key": settings.mcp_api_key},
            params={"tenant_id": tenant_id},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("oauth_token") or data.get("access_token")
        logger.warning("GitHub credential retrieval returned %s", resp.status_code)
    except Exception:
        logger.exception("Failed to retrieve GitHub credentials")
    return None


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# ---------------------------------------------------------------------------
# GitHub tools
# ---------------------------------------------------------------------------


async def list_github_repos(
    tenant_id: str = "auto",
    sort: str = "updated",
    max_results: int = 20,
) -> dict:
    """List repositories accessible to the authenticated GitHub user.

    Args:
        tenant_id: Tenant context (auto-resolved).
        sort: Sort by: updated, created, pushed, full_name.
        max_results: Maximum repos to return (max 100).

    Returns:
        Dict with status and list of repositories.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected. Please connect GitHub in Integrations."}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/user/repos",
                headers=_gh_headers(token),
                params={
                    "sort": sort,
                    "per_page": min(max_results, 100),
                    "type": "all",
                },
            )
            if resp.status_code == 401:
                return {"status": "error", "error": "GitHub token expired. Please reconnect in Integrations."}
            resp.raise_for_status()
            repos = resp.json()
            return {
                "status": "success",
                "count": len(repos),
                "repos": [
                    {
                        "full_name": r["full_name"],
                        "description": r.get("description") or "",
                        "language": r.get("language"),
                        "updated_at": r.get("updated_at"),
                        "default_branch": r.get("default_branch"),
                        "private": r.get("private"),
                        "open_issues_count": r.get("open_issues_count", 0),
                    }
                    for r in repos
                ],
            }
    except Exception as e:
        logger.exception("GitHub list repos failed: %s", e)
        return {"status": "error", "error": str(e)}


async def get_github_repo(
    repo: str,
    tenant_id: str = "auto",
) -> dict:
    """Get details about a specific GitHub repository.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with repo details including stats, default branch, topics.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}",
                headers=_gh_headers(token),
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"Repository '{repo}' not found."}
            if resp.status_code == 401:
                return {"status": "error", "error": "GitHub token expired."}
            resp.raise_for_status()
            r = resp.json()
            return {
                "status": "success",
                "repo": {
                    "full_name": r["full_name"],
                    "description": r.get("description") or "",
                    "language": r.get("language"),
                    "default_branch": r.get("default_branch"),
                    "private": r.get("private"),
                    "stars": r.get("stargazers_count", 0),
                    "forks": r.get("forks_count", 0),
                    "open_issues": r.get("open_issues_count", 0),
                    "topics": r.get("topics", []),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                    "pushed_at": r.get("pushed_at"),
                },
            }
    except Exception as e:
        logger.exception("GitHub get repo failed: %s", e)
        return {"status": "error", "error": str(e)}


async def list_github_issues(
    repo: str,
    state: str = "open",
    labels: str = "",
    max_results: int = 20,
    tenant_id: str = "auto",
) -> dict:
    """List issues in a GitHub repository.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        state: Filter by state: open, closed, all.
        labels: Comma-separated label filter (e.g. "bug,enhancement").
        max_results: Maximum issues to return.
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with list of issues.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        params = {
            "state": state,
            "per_page": min(max_results, 100),
            "sort": "updated",
            "direction": "desc",
        }
        if labels:
            params["labels"] = labels

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/issues",
                headers=_gh_headers(token),
                params=params,
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"Repository '{repo}' not found."}
            resp.raise_for_status()
            issues = resp.json()
            # Filter out pull requests (GitHub API returns PRs as issues)
            issues = [i for i in issues if "pull_request" not in i]
            return {
                "status": "success",
                "count": len(issues),
                "issues": [
                    {
                        "number": i["number"],
                        "title": i["title"],
                        "state": i["state"],
                        "author": i["user"]["login"],
                        "labels": [l["name"] for l in i.get("labels", [])],
                        "created_at": i["created_at"],
                        "updated_at": i["updated_at"],
                        "comments": i.get("comments", 0),
                        "body_preview": (i.get("body") or "")[:300],
                    }
                    for i in issues
                ],
            }
    except Exception as e:
        logger.exception("GitHub list issues failed: %s", e)
        return {"status": "error", "error": str(e)}


async def get_github_issue(
    repo: str,
    issue_number: int,
    tenant_id: str = "auto",
) -> dict:
    """Get details of a specific GitHub issue including comments.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        issue_number: The issue number.
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with issue details and comments.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        headers = _gh_headers(token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get issue
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/issues/{issue_number}",
                headers=headers,
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"Issue #{issue_number} not found in {repo}."}
            resp.raise_for_status()
            issue = resp.json()

            # Get comments
            comments = []
            if issue.get("comments", 0) > 0:
                c_resp = await client.get(
                    f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments",
                    headers=headers,
                    params={"per_page": 30},
                )
                if c_resp.status_code == 200:
                    comments = [
                        {
                            "author": c["user"]["login"],
                            "body": c["body"][:500],
                            "created_at": c["created_at"],
                        }
                        for c in c_resp.json()
                    ]

            return {
                "status": "success",
                "issue": {
                    "number": issue["number"],
                    "title": issue["title"],
                    "state": issue["state"],
                    "author": issue["user"]["login"],
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "assignees": [a["login"] for a in issue.get("assignees", [])],
                    "milestone": (issue.get("milestone") or {}).get("title"),
                    "body": (issue.get("body") or "")[:2000],
                    "created_at": issue["created_at"],
                    "updated_at": issue["updated_at"],
                    "comments_count": issue.get("comments", 0),
                    "comments": comments,
                },
            }
    except Exception as e:
        logger.exception("GitHub get issue failed: %s", e)
        return {"status": "error", "error": str(e)}


async def list_github_pull_requests(
    repo: str,
    state: str = "open",
    max_results: int = 20,
    tenant_id: str = "auto",
) -> dict:
    """List pull requests in a GitHub repository.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        state: Filter by state: open, closed, all.
        max_results: Maximum PRs to return.
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with list of pull requests.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/pulls",
                headers=_gh_headers(token),
                params={
                    "state": state,
                    "per_page": min(max_results, 100),
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"Repository '{repo}' not found."}
            resp.raise_for_status()
            prs = resp.json()
            return {
                "status": "success",
                "count": len(prs),
                "pull_requests": [
                    {
                        "number": pr["number"],
                        "title": pr["title"],
                        "state": pr["state"],
                        "author": pr["user"]["login"],
                        "branch": pr["head"]["ref"],
                        "base": pr["base"]["ref"],
                        "draft": pr.get("draft", False),
                        "created_at": pr["created_at"],
                        "updated_at": pr["updated_at"],
                        "mergeable_state": pr.get("mergeable_state"),
                    }
                    for pr in prs
                ],
            }
    except Exception as e:
        logger.exception("GitHub list PRs failed: %s", e)
        return {"status": "error", "error": str(e)}


async def get_github_pull_request(
    repo: str,
    pr_number: int,
    tenant_id: str = "auto",
) -> dict:
    """Get details of a specific pull request including review status.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        pr_number: The pull request number.
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with PR details, files changed, and reviews.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        headers = _gh_headers(token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get PR details
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}",
                headers=headers,
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"PR #{pr_number} not found in {repo}."}
            resp.raise_for_status()
            pr = resp.json()

            # Get files changed
            files_resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files",
                headers=headers,
                params={"per_page": 50},
            )
            files = []
            if files_resp.status_code == 200:
                files = [
                    {
                        "filename": f["filename"],
                        "status": f["status"],
                        "additions": f["additions"],
                        "deletions": f["deletions"],
                    }
                    for f in files_resp.json()
                ]

            # Get reviews
            reviews_resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews",
                headers=headers,
            )
            reviews = []
            if reviews_resp.status_code == 200:
                reviews = [
                    {
                        "author": rv["user"]["login"],
                        "state": rv["state"],
                        "body": (rv.get("body") or "")[:300],
                    }
                    for rv in reviews_resp.json()
                    if rv["state"] != "PENDING"
                ]

            return {
                "status": "success",
                "pull_request": {
                    "number": pr["number"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "author": pr["user"]["login"],
                    "branch": pr["head"]["ref"],
                    "base": pr["base"]["ref"],
                    "body": (pr.get("body") or "")[:2000],
                    "draft": pr.get("draft", False),
                    "mergeable": pr.get("mergeable"),
                    "additions": pr.get("additions", 0),
                    "deletions": pr.get("deletions", 0),
                    "changed_files": pr.get("changed_files", 0),
                    "created_at": pr["created_at"],
                    "updated_at": pr["updated_at"],
                    "files": files,
                    "reviews": reviews,
                },
            }
    except Exception as e:
        logger.exception("GitHub get PR failed: %s", e)
        return {"status": "error", "error": str(e)}


async def read_github_file(
    repo: str,
    path: str,
    ref: str = "",
    tenant_id: str = "auto",
) -> dict:
    """Read a file's content from a GitHub repository.

    Args:
        repo: Full repository name (e.g. "owner/repo-name").
        path: File path within the repo (e.g. "src/main.py").
        ref: Branch, tag, or commit SHA (defaults to repo's default branch).
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with file content.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        params = {}
        if ref:
            params["ref"] = ref

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/contents/{path}",
                headers=_gh_headers(token),
                params=params,
            )
            if resp.status_code == 404:
                return {"status": "error", "error": f"File '{path}' not found in {repo}."}
            resp.raise_for_status()
            data = resp.json()

            if data.get("type") == "dir":
                # Return directory listing
                return {
                    "status": "success",
                    "type": "directory",
                    "path": path,
                    "entries": [
                        {"name": e["name"], "type": e["type"], "size": e.get("size", 0)}
                        for e in data
                    ] if isinstance(data, list) else [],
                }

            import base64
            content = ""
            if data.get("encoding") == "base64" and data.get("content"):
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")

            # Truncate very large files
            if len(content) > 10000:
                content = content[:10000] + "\n\n... [truncated, file too large] ..."

            return {
                "status": "success",
                "type": "file",
                "path": data.get("path", path),
                "size": data.get("size", 0),
                "content": content,
            }
    except Exception as e:
        logger.exception("GitHub read file failed: %s", e)
        return {"status": "error", "error": str(e)}


async def search_github_code(
    query: str,
    repo: str = "",
    language: str = "",
    max_results: int = 10,
    tenant_id: str = "auto",
) -> dict:
    """Search for code across GitHub repositories.

    Args:
        query: Search query string.
        repo: Limit search to a specific repo (e.g. "owner/repo-name").
        language: Filter by programming language.
        max_results: Maximum results to return.
        tenant_id: Tenant context (auto-resolved).

    Returns:
        Dict with matching code snippets and file locations.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_github_token(tenant_id)
    if not token:
        return {"status": "error", "error": "GitHub not connected."}

    try:
        q = query
        if repo:
            q += f" repo:{repo}"
        if language:
            q += f" language:{language}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/search/code",
                headers=_gh_headers(token),
                params={"q": q, "per_page": min(max_results, 30)},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "success",
                "total_count": data.get("total_count", 0),
                "results": [
                    {
                        "repo": item["repository"]["full_name"],
                        "path": item["path"],
                        "name": item["name"],
                        "url": item["html_url"],
                    }
                    for item in data.get("items", [])
                ],
            }
    except Exception as e:
        logger.exception("GitHub search code failed: %s", e)
        return {"status": "error", "error": str(e)}
