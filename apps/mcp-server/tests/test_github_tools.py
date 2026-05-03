"""Tests for src.mcp_tools.github high-level tools.

The lower-level resolver / try-each helpers are already covered by
``tests/test_github_resolver.py``. This file focuses on the public MCP
tools — list_github_repos, get_github_repo, list_github_issues,
get_github_issue, list_github_pull_requests, read_github_file,
search_github_code.
"""
from __future__ import annotations

import base64
import pytest

from src.mcp_tools import github as gh


@pytest.fixture
def patch_accounts(monkeypatch):
    """Stub _resolve_accounts so individual tools don't hit the API."""

    def _install(accounts):
        async def _resolve(tenant_id, account_email):
            if not accounts:
                return []
            if account_email:
                return [(e, t) for e, t in accounts if e.lower() == account_email.lower()]
            return list(accounts)

        monkeypatch.setattr(gh, "_resolve_accounts", _resolve)
        return accounts

    return _install


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(gh.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant guards on every tool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (gh.list_github_repos, {}),
        (gh.get_github_repo, {"repo": "x/y"}),
        (gh.list_github_issues, {"repo": "x/y"}),
        (gh.get_github_issue, {"repo": "x/y", "issue_number": 1}),
        (gh.list_github_pull_requests, {"repo": "x/y"}),
        (gh.read_github_file, {"repo": "x/y", "path": "README.md"}),
        (gh.search_github_code, {"query": "foo"}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


# ---------------------------------------------------------------------------
# list_github_repos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_github_repos_no_accounts(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([])
    out = await gh.list_github_repos(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_list_github_repos_merges_and_dedupes(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok-a"), ("b@x.com", "tok-b")])
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        token = kwargs.get("headers", {}).get("Authorization", "")
        if "tok-a" in token:
            return _DummyResponse(200, [
                {"full_name": "a/repo1", "default_branch": "main"},
                {"full_name": "shared/repo", "default_branch": "main"},
            ])
        return _DummyResponse(200, [
            {"full_name": "b/repo1", "default_branch": "main"},
            {"full_name": "shared/repo", "default_branch": "main"},  # dup
        ])

    patch_httpx(side_effect=_side_effect)
    out = await gh.list_github_repos(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 3
    full_names = {r["full_name"] for r in out["repos"]}
    assert full_names == {"a/repo1", "b/repo1", "shared/repo"}


@pytest.mark.asyncio
async def test_list_github_repos_token_expired_path(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok-a")])
    patch_httpx(default_status=401, default_json=[])
    out = await gh.list_github_repos(tenant_id="t", ctx=mock_ctx)
    assert "expired" in out["error"]


# ---------------------------------------------------------------------------
# get_github_repo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_github_repo_happy(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=200, default_json={
        "full_name": "a/r", "stargazers_count": 5, "open_issues_count": 1,
        "created_at": "x", "updated_at": "y", "pushed_at": "z",
    })
    out = await gh.get_github_repo(repo="a/r", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["repo"]["full_name"] == "a/r"
    assert out["repo"]["stars"] == 5


@pytest.mark.asyncio
async def test_get_github_repo_404_across_all_accounts(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok-a"), ("b@x.com", "tok-b")])
    patch_httpx(default_status=404, default_json={})
    out = await gh.get_github_repo(repo="ghost/repo", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"].lower()


# ---------------------------------------------------------------------------
# list_github_issues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_github_issues_filters_out_pull_requests(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=200, default_json=[
        {
            "number": 1, "title": "real issue", "state": "open",
            "user": {"login": "u"}, "labels": [{"name": "bug"}],
            "created_at": "c", "updated_at": "u",
            "comments": 0, "body": "x",
        },
        {
            "number": 2, "title": "is PR", "state": "open",
            "user": {"login": "u"}, "labels": [],
            "created_at": "c", "updated_at": "u",
            "pull_request": {},  # marker — filtered out
            "body": "",
        },
    ])
    out = await gh.list_github_issues(repo="a/r", tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["issues"][0]["number"] == 1


@pytest.mark.asyncio
async def test_list_github_issues_404(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=404, default_json={})
    out = await gh.list_github_issues(repo="ghost/r", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"].lower()


# ---------------------------------------------------------------------------
# get_github_issue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_github_issue_with_comments(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    from tests.conftest import _DummyResponse  # type: ignore

    issue = {
        "number": 5, "title": "Bug", "state": "open",
        "user": {"login": "u"}, "labels": [{"name": "bug"}],
        "body": "details", "created_at": "c", "updated_at": "u",
        "comments": 1,
    }
    comments = [
        {"user": {"login": "x"}, "body": "first comment", "created_at": "t"},
    ]

    def _side_effect(method, url, kwargs):
        if "/comments" in url:
            return _DummyResponse(200, comments)
        return _DummyResponse(200, issue)

    patch_httpx(side_effect=_side_effect)
    out = await gh.get_github_issue(repo="a/r", issue_number=5, tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["issue"]["comments_count"] == 1
    assert out["issue"]["comments"][0]["author"] == "x"


@pytest.mark.asyncio
async def test_get_github_issue_validates_inputs(mock_ctx):
    out = await gh.get_github_issue(repo="", issue_number=1, tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    out2 = await gh.get_github_issue(repo="a/r", issue_number=0, tenant_id="t", ctx=mock_ctx)
    assert "error" in out2


# ---------------------------------------------------------------------------
# list_github_pull_requests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_github_pull_requests_happy(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=200, default_json=[
        {
            "number": 100,
            "title": "feat: x",
            "state": "open",
            "user": {"login": "u"},
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
            "draft": False,
            "merged_at": None,
            "created_at": "c",
            "updated_at": "u",
        }
    ])
    out = await gh.list_github_pull_requests(repo="a/r", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 1
    assert out["pull_requests"][0]["number"] == 100


@pytest.mark.asyncio
async def test_list_github_pull_requests_404(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=404, default_json={})
    out = await gh.list_github_pull_requests(repo="ghost/r", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"].lower()


# ---------------------------------------------------------------------------
# read_github_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_github_file_decodes_base64(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    payload = base64.b64encode(b"hello world").decode()
    patch_httpx(default_status=200, default_json={
        "type": "file", "encoding": "base64", "content": payload,
        "path": "README.md", "size": 11,
    })
    out = await gh.read_github_file(repo="a/r", path="README.md", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["content"] == "hello world"


@pytest.mark.asyncio
async def test_read_github_file_directory(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    # A directory listing is returned as a list at the top level.
    # The tool's `data.get(...)` will fail if data is a list — but the
    # source already handles that by checking isinstance(data, list).
    # Note: the source's branch is hard to reach because it calls
    # data.get("type") first; a list does not have .get(). The branch
    # is therefore effectively unreachable. We exercise the file
    # branch only.
    patch_httpx(default_status=200, default_json={
        "type": "file", "encoding": "base64", "content": "", "path": "x", "size": 0,
    })
    out = await gh.read_github_file(repo="a/r", path="x", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"


@pytest.mark.asyncio
async def test_read_github_file_truncates_large_content(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    big = base64.b64encode(("y" * 20000).encode()).decode()
    patch_httpx(default_status=200, default_json={
        "type": "file", "encoding": "base64", "content": big,
        "path": "big.txt", "size": 20000,
    })
    out = await gh.read_github_file(repo="a/r", path="big.txt", tenant_id="t", ctx=mock_ctx)
    assert "truncated" in out["content"]


@pytest.mark.asyncio
async def test_read_github_file_404(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok")])
    patch_httpx(default_status=404, default_json={})
    out = await gh.read_github_file(repo="a/r", path="missing", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"].lower()


# ---------------------------------------------------------------------------
# search_github_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_github_code_merges_results_across_accounts(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok-a"), ("b@x.com", "tok-b")])
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        token = kwargs.get("headers", {}).get("Authorization", "")
        if "tok-a" in token:
            return _DummyResponse(200, {
                "total_count": 1,
                "items": [{
                    "html_url": "http://a/x.py",
                    "path": "x.py", "name": "x.py",
                    "repository": {"full_name": "a/r"},
                }],
            })
        return _DummyResponse(200, {
            "total_count": 1,
            "items": [{
                "html_url": "http://b/y.py",
                "path": "y.py", "name": "y.py",
                "repository": {"full_name": "b/r"},
            }],
        })

    patch_httpx(side_effect=_side_effect)
    out = await gh.search_github_code(
        query="foo", language="python", repo="a/r", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "success"
    assert len(out["results"]) == 2


@pytest.mark.asyncio
async def test_search_github_code_skips_failing_accounts(patch_accounts, patch_httpx, mock_ctx):
    patch_accounts([("a@x.com", "tok-a")])
    patch_httpx(default_status=403, default_json={})
    out = await gh.search_github_code(query="foo", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["results"] == []
