"""Tests for src.mcp_tools.jira.

Five public tools + helpers (_normalize_domain, _build_auth_header).
Stubs ``_get_jira_credentials`` to bypass the credential vault, then
patches ``httpx.AsyncClient`` per scenario.
"""
from __future__ import annotations

import base64
import pytest

from src.mcp_tools import jira as jr


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_normalize_domain_adds_https_and_atlassian():
    assert jr._normalize_domain("acme") == "https://acme.atlassian.net"


def test_normalize_domain_keeps_full_url():
    assert jr._normalize_domain("https://acme.atlassian.net/") == "https://acme.atlassian.net"


def test_normalize_domain_keeps_custom_domain():
    # Already has a dot — treated as a real domain
    assert jr._normalize_domain("https://jira.acme.com") == "https://jira.acme.com"


def test_build_auth_header_is_base64_basic_auth():
    h = jr._build_auth_header("alice@acme.com", "tok")
    assert h.startswith("Basic ")
    decoded = base64.b64decode(h[len("Basic "):]).decode()
    assert decoded == "alice@acme.com:tok"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_creds(monkeypatch):
    def _install(creds):
        async def _get(tid):
            return creds

        monkeypatch.setattr(jr, "_get_jira_credentials", _get)
        return creds

    return _install


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(jr.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant + connected guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (jr.search_jira_issues, {}),
        (jr.get_jira_issue, {"issue_key": "X-1"}),
        (jr.create_jira_issue, {"project_key": "P", "summary": "s"}),
        (jr.update_jira_issue, {"issue_key": "X-1"}),
        (jr.list_jira_projects, {}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


@pytest.mark.asyncio
async def test_search_when_jira_not_connected(monkeypatch, mock_ctx):
    async def _none(tid):
        return None

    monkeypatch.setattr(jr, "_get_jira_credentials", _none)
    out = await jr.search_jira_issues(tenant_id="t", ctx=mock_ctx)
    assert "not connected" in out["error"]


@pytest.mark.asyncio
async def test_search_when_credentials_incomplete(patch_creds, mock_ctx):
    patch_creds({"api_token": "x", "email": ""})
    out = await jr.search_jira_issues(tenant_id="t", ctx=mock_ctx)
    assert "incomplete" in out["error"]


# ---------------------------------------------------------------------------
# search_jira_issues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})
    patch_httpx(default_status=200, default_json={
        "total": 1,
        "issues": [
            {
                "key": "X-1",
                "fields": {
                    "summary": "Bug",
                    "status": {"name": "Open"},
                    "priority": {"name": "High"},
                    "issuetype": {"name": "Bug"},
                    "assignee": {"displayName": "Alice"},
                    "project": {"key": "X"},
                    "updated": "2026-05-01",
                },
            }
        ],
    })
    out = await jr.search_jira_issues(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["issues"][0]["key"] == "X-1"
    assert out["issues"][0]["assignee"] == "Alice"


@pytest.mark.asyncio
async def test_search_handles_401(patch_creds, monkeypatch, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})

    import httpx as real

    class _Resp:
        status_code = 401
        text = "unauth"

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("POST", "http://x")
            raise real.HTTPStatusError("401", request=req, response=real.Response(401, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(jr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await jr.search_jira_issues(tenant_id="t", ctx=mock_ctx)
    assert "authentication" in out["error"].lower()


# ---------------------------------------------------------------------------
# get_jira_issue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_issue_extracts_adf_description_and_comments(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme.atlassian.net"})
    issue_payload = {
        "key": "X-1",
        "fields": {
            "summary": "S",
            "description": {
                "content": [
                    {"content": [{"type": "text", "text": "Hello "}]},
                    {"content": [{"type": "text", "text": "World"}]},
                ]
            },
            "status": {"name": "Open"},
            "priority": {"name": "Low"},
            "issuetype": {"name": "Task"},
            "assignee": None,
            "reporter": {"displayName": "Bob"},
            "project": {"name": "Proj"},
            "labels": ["l1"],
            "comment": {
                "comments": [
                    {
                        "body": {
                            "content": [
                                {"content": [{"type": "text", "text": "first comment"}]}
                            ]
                        },
                        "author": {"displayName": "x"},
                        "created": "now",
                    }
                ]
            },
        },
    }
    patch_httpx(default_status=200, default_json=issue_payload)
    out = await jr.get_jira_issue(issue_key="X-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert "Hello" in out["description"]
    assert out["assignee"] == "Unassigned"
    assert out["comments"][0]["body"] == "first comment"


@pytest.mark.asyncio
async def test_get_issue_404(patch_creds, monkeypatch, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})
    import httpx as real

    class _Resp:
        status_code = 404
        text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("GET", "http://x")
            raise real.HTTPStatusError("404", request=req, response=real.Response(404, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(jr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await jr.get_jira_issue(issue_key="X-1", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


# ---------------------------------------------------------------------------
# create_jira_issue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_issue_validates_required(mock_ctx):
    out = await jr.create_jira_issue(
        project_key="", summary="x", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_create_issue_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})
    client = patch_httpx(default_status=201, default_json={"key": "X-99", "id": "i-99"})
    out = await jr.create_jira_issue(
        project_key="X", summary="Bug",
        description="details", priority="High",
        labels="a, b",
        assignee_email="alice@acme.com",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["key"] == "X-99"
    sent = client.calls[0]["json"]
    assert sent["fields"]["project"]["key"] == "X"
    assert sent["fields"]["priority"]["name"] == "High"
    assert sent["fields"]["labels"] == ["a", "b"]


# ---------------------------------------------------------------------------
# update_jira_issue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_issue_fields_and_status_and_comment(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})

    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        if method == "PUT":
            return _DummyResponse(204, {})
        if method == "GET" and "/transitions" in url:
            return _DummyResponse(200, {"transitions": [{"id": "31", "name": "Done"}]})
        if method == "POST" and "/transitions" in url:
            return _DummyResponse(204, {})
        if method == "POST" and "/comment" in url:
            return _DummyResponse(201, {})
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_side_effect)

    out = await jr.update_jira_issue(
        issue_key="X-1",
        tenant_id="t",
        summary="new",
        status="Done",
        comment="moved",
        priority="High",
        assignee_email="bob@x",
        description="text",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert "fields updated" in out["updates"]
    assert any("Done" in u for u in out["updates"])
    assert "comment added" in out["updates"]


@pytest.mark.asyncio
async def test_update_issue_unknown_status_lists_options(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})
    from tests.conftest import _DummyResponse  # type: ignore

    def _side_effect(method, url, kwargs):
        if method == "GET" and "/transitions" in url:
            return _DummyResponse(200, {"transitions": [{"id": "1", "name": "Open"}]})
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_side_effect)
    out = await jr.update_jira_issue(
        issue_key="X-1", tenant_id="t", status="WeirdStatus", ctx=mock_ctx
    )
    assert any("not available" in u for u in out["updates"])


# ---------------------------------------------------------------------------
# list_jira_projects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_projects_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})
    patch_httpx(default_status=200, default_json=[
        {"key": "P1", "name": "Proj 1", "projectTypeKey": "software"},
        {"key": "P2", "name": "Proj 2"},
    ])
    out = await jr.list_jira_projects(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 2
    assert out["projects"][0]["type"] == "software"


@pytest.mark.asyncio
async def test_list_projects_401(patch_creds, monkeypatch, mock_ctx):
    patch_creds({"api_token": "t", "email": "a@b", "domain": "acme"})

    import httpx as real

    class _Resp:
        status_code = 401
        text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("GET", "http://x")
            raise real.HTTPStatusError("401", request=req, response=real.Response(401, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(jr.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await jr.list_jira_projects(tenant_id="t", ctx=mock_ctx)
    assert "authentication" in out["error"].lower()
