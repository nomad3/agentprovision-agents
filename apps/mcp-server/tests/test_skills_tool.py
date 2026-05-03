"""Tests for src.mcp_tools.skills.

Each tool is a thin httpx-based REST passthrough. We mock the
``httpx.AsyncClient`` call site and assert the URL, headers, and
response shape.
"""
from __future__ import annotations

import json
import pytest

from src.mcp_tools import skills as sk


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    holder = {}

    def _install(responses=None, default_status=200, default_json=None, side_effect=None):
        client = make_client(
            responses=responses,
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        holder["client"] = client
        monkeypatch.setattr(sk.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_skills_returns_normalized_records(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(
        default_status=200,
        default_json=[
            {"name": "Calc", "description": "Math", "inputs": [{"name": "x"}]},
            {"name": "Sum", "description": "Adds"},
        ],
    )

    out = await sk.list_skills(tenant_id="t", ctx=mock_ctx)

    assert out["status"] == "success"
    assert out["count"] == 2
    assert out["skills"][1]["inputs"] == []


@pytest.mark.asyncio
async def test_list_skills_returns_error_on_non_200(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await sk.list_skills(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_list_skills_handles_exception(monkeypatch, mock_ctx, patch_settings):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(sk.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    out = await sk.list_skills(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# run_skill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_skill_validates_required_args(mock_ctx):
    assert "error" in await sk.run_skill(skill_name="", inputs="{}", ctx=mock_ctx)
    assert "error" in await sk.run_skill(skill_name="x", inputs="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_run_skill_rejects_invalid_json_inputs(mock_ctx):
    out = await sk.run_skill(skill_name="x", inputs="not-json", ctx=mock_ctx)
    assert "Invalid JSON" in out["error"]


@pytest.mark.asyncio
async def test_run_skill_happy_path(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"output": 42})
    out = await sk.run_skill(skill_name="calc", inputs='{"x": 1}', ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["output"] == 42
    assert client.calls[0]["json"] == {"skill_name": "calc", "inputs": {"x": 1}}


@pytest.mark.asyncio
async def test_run_skill_propagates_http_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await sk.run_skill(skill_name="calc", inputs='{}', ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# read_library_skill
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_library_skill_requires_slug(mock_ctx):
    assert "error" in await sk.read_library_skill(slug="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_read_library_skill_404(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=404, default_json={})
    out = await sk.read_library_skill(slug="missing", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_read_library_skill_happy(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=200, default_json={"slug": "x", "name": "X", "body": "..."})
    out = await sk.read_library_skill(slug="x", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["slug"] == "x"


# ---------------------------------------------------------------------------
# update_skill_definition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_skill_definition_validates_required(mock_ctx):
    assert "error" in await sk.update_skill_definition(
        skill_slug="", new_prompt="x", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sk.update_skill_definition(
        skill_slug="x", new_prompt="   ", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sk.update_skill_definition(
        skill_slug="x", new_prompt="x", tenant_id="", ctx=mock_ctx
    )


@pytest.mark.asyncio
async def test_update_skill_definition_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"slug": "s", "body": "y"})
    out = await sk.update_skill_definition(
        skill_slug="s", new_prompt="hello", reason="r", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "success"
    payload = client.calls[0]["json"]
    assert payload["slug"] == "s"
    assert payload["new_prompt"] == "hello"
    assert payload["reason"] == "r"
    assert payload["tenant_id"] == "t"


@pytest.mark.asyncio
async def test_update_skill_definition_http_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=403, default_json={})
    out = await sk.update_skill_definition(
        skill_slug="s", new_prompt="x", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


# ---------------------------------------------------------------------------
# update_agent_definition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_agent_definition_validates_inputs(mock_ctx):
    assert "error" in await sk.update_agent_definition(
        agent_id="", updates_json="{}", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sk.update_agent_definition(
        agent_id="a", updates_json="", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sk.update_agent_definition(
        agent_id="a", updates_json="{}", tenant_id="", ctx=mock_ctx
    )
    assert "Invalid JSON" in (await sk.update_agent_definition(
        agent_id="a", updates_json="not-json", tenant_id="t", ctx=mock_ctx
    ))["error"]
    # Empty dict / non-dict
    assert "non-empty" in (await sk.update_agent_definition(
        agent_id="a", updates_json="[]", tenant_id="t", ctx=mock_ctx
    ))["error"]
    assert "non-empty" in (await sk.update_agent_definition(
        agent_id="a", updates_json="{}", tenant_id="t", ctx=mock_ctx
    ))["error"]


@pytest.mark.asyncio
async def test_update_agent_definition_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"id": "a-1"})
    out = await sk.update_agent_definition(
        agent_id="a-1",
        updates_json=json.dumps({"description": "new"}),
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    payload = client.calls[0]["json"]
    assert payload["updates"] == {"description": "new"}


# ---------------------------------------------------------------------------
# list_library_revisions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_library_revisions_requires_tenant(mock_ctx):
    out = await sk.list_library_revisions(tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_list_library_revisions_clamps_limit(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await sk.list_library_revisions(limit=9999, tenant_id="t", ctx=mock_ctx)
    assert client.calls[0]["params"]["limit"] == 500

    client2 = patch_httpx(default_status=200, default_json=[])
    await sk.list_library_revisions(limit=0, tenant_id="t", ctx=mock_ctx)
    # 0 is falsy → falls back to default 20 in `int(limit or 20)`
    assert client2.calls[0]["params"]["limit"] == 20


@pytest.mark.asyncio
async def test_list_library_revisions_passes_filters(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json=[])
    await sk.list_library_revisions(
        target_type="skill", target_ref="my-skill", tenant_id="t", ctx=mock_ctx
    )
    params = client.calls[0]["params"]
    assert params["target_type"] == "skill"
    assert params["target_ref"] == "my-skill"


@pytest.mark.asyncio
async def test_list_library_revisions_error_response(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await sk.list_library_revisions(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# recall_memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_memory_requires_query(mock_ctx):
    out = await sk.recall_memory(query="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_recall_memory_happy(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(default_status=200, default_json={"results": [{"id": 1}]})
    out = await sk.recall_memory(query="hello", types="entity", limit=5, tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert client.calls[0]["params"]["q"] == "hello"
    assert client.calls[0]["params"]["types"] == "entity"


@pytest.mark.asyncio
async def test_recall_memory_returns_empty_on_failure(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    out = await sk.recall_memory(query="hello", ctx=mock_ctx)
    assert out["results"] == []
