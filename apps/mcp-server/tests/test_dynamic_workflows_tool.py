"""Tests for src.mcp_tools.dynamic_workflows.

The module is a thin REST passthrough — every tool calls ``_api_call``
which talks to the internal /api/v1/dynamic-workflows endpoints. We
mock the httpx layer and assert (a) the right URL/method is invoked,
(b) the response is shaped the way the tool documents.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import dynamic_workflows as dw


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    """Patch dw.httpx.AsyncClient to return our DummyHttpxClient."""
    holder = {}

    def _install(responses=None, default_status=200, default_json=None, side_effect=None):
        client = make_client(
            responses=responses,
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        holder["client"] = client
        monkeypatch.setattr(
            dw.httpx, "AsyncClient", lambda *a, **kw: client
        )
        return client

    return _install


# ---------------------------------------------------------------------------
# _api_call helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_call_get_attaches_headers(patch_httpx, DummyResponse):
    client = patch_httpx(default_status=200, default_json={"ok": True})

    out = await dw._api_call("get", "/internal/list", "tenant-1")

    assert out == {"ok": True}
    assert client.calls[0]["method"] == "GET"
    assert client.calls[0]["headers"]["X-Tenant-Id"] == "tenant-1"
    assert "X-Internal-Key" in client.calls[0]["headers"]
    # GET should not pass json
    assert "json" not in client.calls[0]


@pytest.mark.asyncio
async def test_api_call_post_attaches_json(patch_httpx):
    client = patch_httpx(default_status=201, default_json={"id": "wf-1", "name": "x"})

    out = await dw._api_call("post", "/internal/create", "tenant-1", {"name": "x"})

    assert out["id"] == "wf-1"
    assert client.calls[0]["json"] == {"name": "x"}


@pytest.mark.asyncio
async def test_api_call_204_returns_status_success(patch_httpx):
    patch_httpx(default_status=204)
    out = await dw._api_call("delete", "/internal/wf-1", "tenant-1")
    assert out == {"status": "success"}


@pytest.mark.asyncio
async def test_api_call_error_status_returns_error_dict(patch_httpx, DummyResponse):
    patch_httpx(
        default_status=500,
        default_json={},
    )
    # Override the default to include a text body for the error path
    out = await dw._api_call("get", "/internal/list", "tenant-1")
    assert "error" in out
    assert "500" in out["error"]


# ---------------------------------------------------------------------------
# create_dynamic_workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_dynamic_workflow_happy_path(patch_httpx, mock_ctx):
    client = patch_httpx(
        default_status=201,
        default_json={"id": "wf-99", "name": "Test"},
    )

    result = await dw.create_dynamic_workflow(
        name="Test",
        description="hello",
        steps=[{"id": "s1", "type": "mcp_tool"}],
        trigger_type="cron",
        trigger_schedule="0 8 * * *",
        tenant_id="tenant-1",
        ctx=mock_ctx,
    )

    assert result["status"] == "created"
    assert result["id"] == "wf-99"
    assert result["steps"] == 1
    assert result["trigger"] == "cron"

    payload = client.calls[0]["json"]
    assert payload["name"] == "Test"
    assert payload["definition"]["steps"][0]["id"] == "s1"
    assert payload["trigger_config"] == {"type": "cron", "schedule": "0 8 * * *"}


@pytest.mark.asyncio
async def test_create_dynamic_workflow_defaults_to_empty_steps(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=201, default_json={"id": "wf-1", "name": "n"})

    result = await dw.create_dynamic_workflow(name="n", tenant_id="t", ctx=mock_ctx)

    assert result["steps"] == 0
    payload = client.calls[0]["json"]
    assert payload["definition"]["steps"] == []
    assert payload["tags"] == []


@pytest.mark.asyncio
async def test_create_dynamic_workflow_propagates_api_error(patch_httpx, mock_ctx):
    patch_httpx(default_status=400, default_json={})
    out = await dw.create_dynamic_workflow(name="n", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# list_dynamic_workflows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_dynamic_workflows_normalizes_records(patch_httpx, mock_ctx):
    patch_httpx(
        default_status=200,
        default_json=[
            {
                "id": "wf-1",
                "name": "A",
                "status": "active",
                "definition": {"steps": [{"id": "s1"}, {"id": "s2"}]},
                "trigger_config": {"type": "cron"},
                "run_count": 5,
                "success_rate": 0.8,
                "tags": ["daily"],
            }
        ],
    )

    out = await dw.list_dynamic_workflows(tenant_id="t", ctx=mock_ctx)

    assert out["count"] == 1
    wf = out["workflows"][0]
    assert wf["steps"] == 2
    assert wf["trigger"] == "cron"
    assert wf["tags"] == ["daily"]


@pytest.mark.asyncio
async def test_list_dynamic_workflows_with_status_filter_appends_query(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json=[])
    await dw.list_dynamic_workflows(status="active", tenant_id="t", ctx=mock_ctx)
    assert "status=active" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_list_dynamic_workflows_returns_api_error_dict(patch_httpx, mock_ctx):
    patch_httpx(default_status=500, default_json={})
    out = await dw.list_dynamic_workflows(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# run_dynamic_workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_dynamic_workflow_returns_started(patch_httpx, mock_ctx):
    client = patch_httpx(
        default_status=200,
        default_json={"id": "run-42"},
    )
    out = await dw.run_dynamic_workflow(
        workflow_id="wf-1", input_data={"x": 1}, tenant_id="t", ctx=mock_ctx
    )
    assert out == {"status": "started", "run_id": "run-42", "workflow_id": "wf-1"}
    assert client.calls[0]["json"] == {"input_data": {"x": 1}}


@pytest.mark.asyncio
async def test_run_dynamic_workflow_default_input_data(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"id": "r-1"})
    await dw.run_dynamic_workflow(workflow_id="wf-1", tenant_id="t", ctx=mock_ctx)
    assert client.calls[0]["json"] == {"input_data": {}}


@pytest.mark.asyncio
async def test_run_dynamic_workflow_error(patch_httpx, mock_ctx):
    patch_httpx(default_status=500, default_json={})
    out = await dw.run_dynamic_workflow(workflow_id="wf-1", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# get_workflow_run_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_workflow_run_status_summarizes_steps(patch_httpx, mock_ctx):
    patch_httpx(
        default_status=200,
        default_json={
            "run": {
                "status": "completed",
                "started_at": "2026-05-03T10:00:00Z",
                "duration_ms": 1234,
                "total_tokens": 500,
                "total_cost_usd": 0.01,
            },
            "steps": [
                {
                    "step_id": "s1",
                    "step_type": "mcp_tool",
                    "status": "ok",
                    "duration_ms": 100,
                    "tokens_used": 200,
                }
            ],
        },
    )

    out = await dw.get_workflow_run_status(run_id="r-1", tenant_id="t", ctx=mock_ctx)

    assert out["status"] == "completed"
    assert out["total_tokens"] == 500
    assert out["steps"][0]["id"] == "s1"
    assert out["steps"][0]["tokens"] == 200


@pytest.mark.asyncio
async def test_get_workflow_run_status_returns_error(patch_httpx, mock_ctx):
    patch_httpx(default_status=404, default_json={})
    out = await dw.get_workflow_run_status(run_id="r-1", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# activate / delete / install_template
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_dynamic_workflow_passthrough(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"status": "active"})
    out = await dw.activate_dynamic_workflow(workflow_id="wf-1", tenant_id="t", ctx=mock_ctx)
    assert out == {"status": "active"}
    assert client.calls[0]["url"].endswith("/wf-1/activate")
    assert client.calls[0]["method"] == "POST"


@pytest.mark.asyncio
async def test_delete_dynamic_workflow_returns_friendly_message(patch_httpx, mock_ctx):
    patch_httpx(default_status=204)
    out = await dw.delete_dynamic_workflow(workflow_id="wf-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "deleted"
    assert out["workflow_id"] == "wf-1"


@pytest.mark.asyncio
async def test_install_workflow_template_summarizes(patch_httpx, mock_ctx):
    patch_httpx(
        default_status=200,
        default_json={
            "id": "wf-100",
            "name": "Daily Brief",
            "definition": {"steps": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]},
        },
    )
    out = await dw.install_workflow_template(template_id="tpl-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "installed"
    assert out["steps"] == 3


# ---------------------------------------------------------------------------
# update_dynamic_workflow — most logic-heavy of the bunch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_dynamic_workflow_keeps_omitted_fields(patch_httpx, mock_ctx):
    """Calling update with only ``name`` overridden should keep the
    existing description, definition, trigger config, and tags."""
    fetch_resp = {
        "name": "Old",
        "description": "Old desc",
        "definition": {"steps": [{"id": "s0"}]},
        "trigger_config": {"type": "cron", "schedule": "0 8 * * *"},
        "tags": ["x"],
    }
    update_resp = {
        "id": "wf-1",
        "name": "New",
        "definition": {"steps": [{"id": "s0"}]},
        "trigger_config": {"type": "cron"},
    }

    calls = {"i": 0}

    def _side_effect(method, url, kwargs):
        calls["i"] += 1
        from tests.conftest import _DummyResponse  # type: ignore
        if method == "GET":
            return _DummyResponse(200, fetch_resp)
        return _DummyResponse(200, update_resp)

    client = patch_httpx(side_effect=_side_effect)

    out = await dw.update_dynamic_workflow(
        workflow_id="wf-1",
        tenant_id="t",
        name="New",
        ctx=mock_ctx,
    )

    assert out["status"] == "updated"
    # Second call should be a PUT with merged payload
    put_call = client.calls[1]
    assert put_call["method"] == "PUT"
    payload = put_call["json"]
    assert payload["name"] == "New"
    assert payload["description"] == "Old desc"  # kept
    assert payload["definition"]["steps"][0]["id"] == "s0"  # kept
    assert payload["trigger_config"]["schedule"] == "0 8 * * *"
    assert payload["tags"] == ["x"]


@pytest.mark.asyncio
async def test_update_dynamic_workflow_propagates_fetch_error(patch_httpx, mock_ctx):
    patch_httpx(default_status=404, default_json={})
    out = await dw.update_dynamic_workflow(workflow_id="wf-1", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_update_dynamic_workflow_replaces_definition(patch_httpx, mock_ctx):
    fetch_resp = {
        "name": "Old",
        "description": "",
        "definition": {"steps": [{"id": "old"}]},
        "trigger_config": {"type": "manual"},
        "tags": [],
    }
    update_resp = {
        "id": "wf-1",
        "name": "Old",
        "definition": {"steps": [{"id": "new1"}, {"id": "new2"}]},
        "trigger_config": {"type": "manual"},
    }

    def _side_effect(method, url, kwargs):
        from tests.conftest import _DummyResponse  # type: ignore
        if method == "GET":
            return _DummyResponse(200, fetch_resp)
        return _DummyResponse(200, update_resp)

    client = patch_httpx(side_effect=_side_effect)

    new_def = {"steps": [{"id": "new1"}, {"id": "new2"}]}
    out = await dw.update_dynamic_workflow(
        workflow_id="wf-1",
        tenant_id="t",
        definition=new_def,
        ctx=mock_ctx,
    )

    assert out["steps"] == 2
    put_call = client.calls[1]
    assert put_call["json"]["definition"] == new_def
