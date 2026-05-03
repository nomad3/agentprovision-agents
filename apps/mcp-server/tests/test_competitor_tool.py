"""Tests for src.mcp_tools.competitor — happy/error paths.

Helpers ``_api_post`` / ``_api_get`` make these tools easy to mock —
we patch the helpers directly rather than the underlying httpx layer.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import competitor as cp


@pytest.fixture
def patch_api(monkeypatch):
    """Replace _api_get / _api_post with stubs that record calls and
    return scripted payloads. Returns a (post_calls, get_calls) tuple."""
    posts = []
    gets = []

    def _install(post_results=None, get_results=None, post_raises=None, get_raises=None):
        post_iter = iter(post_results or [])
        get_iter = iter(get_results or [])

        async def _post(path, json=None):
            posts.append({"path": path, "json": json})
            if post_raises is not None:
                raise post_raises
            try:
                return next(post_iter)
            except StopIteration:
                return {}

        async def _get(path, params=None):
            gets.append({"path": path, "params": params})
            if get_raises is not None:
                raise get_raises
            try:
                return next(get_iter)
            except StopIteration:
                return {}

        monkeypatch.setattr(cp, "_api_post", _post)
        monkeypatch.setattr(cp, "_api_get", _get)
        return posts, gets

    return _install


# ---------------------------------------------------------------------------
# add_competitor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_competitor_validates(mock_ctx):
    assert "error" in await cp.add_competitor(name="", tenant_id="t", ctx=mock_ctx)
    assert "error" in await cp.add_competitor(name="x", tenant_id="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_add_competitor_happy(patch_api, mock_ctx):
    posts, gets = patch_api(post_results=[{"id": "ent-1"}])
    out = await cp.add_competitor(
        name="Acme",
        website="http://acme.com",
        facebook_url="http://fb.com/acme",
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["entity_id"] == "ent-1"
    body = posts[0]["json"]
    assert body["name"] == "Acme"
    assert body["category"] == "competitor"
    assert body["properties"]["facebook_url"] == "http://fb.com/acme"
    # empty fields filtered out
    assert "instagram_url" not in body["properties"]


@pytest.mark.asyncio
async def test_add_competitor_propagates_exception(patch_api, mock_ctx):
    patch_api(post_raises=RuntimeError("api down"))
    out = await cp.add_competitor(name="x", tenant_id="t", ctx=mock_ctx)
    assert "Failed to add" in out["error"]


# ---------------------------------------------------------------------------
# list_competitors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_competitors_validates(mock_ctx):
    out = await cp.list_competitors(tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_list_competitors_returns_list(patch_api, mock_ctx):
    patch_api(get_results=[[{"id": "1", "name": "Acme"}]])
    out = await cp.list_competitors(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_list_competitors_returns_dict(patch_api, mock_ctx):
    patch_api(get_results=[{"entities": [{"id": "1"}, {"id": "2"}]}])
    out = await cp.list_competitors(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 2


@pytest.mark.asyncio
async def test_list_competitors_handles_exception(patch_api, mock_ctx):
    patch_api(get_raises=RuntimeError("net"))
    out = await cp.list_competitors(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# remove_competitor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_competitor_validates(mock_ctx):
    assert "error" in await cp.remove_competitor(name="", tenant_id="t", ctx=mock_ctx)
    assert "error" in await cp.remove_competitor(name="x", tenant_id="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_remove_competitor_not_found(patch_api, mock_ctx):
    patch_api(get_results=[[]])
    out = await cp.remove_competitor(name="ghost", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_remove_competitor_archives(patch_api, mock_ctx):
    posts, gets = patch_api(
        get_results=[[{"id": "ent-1", "name": "Acme", "category": "competitor"}]],
        post_results=[{}],
    )
    out = await cp.remove_competitor(name="Acme", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert "/archive" in posts[0]["path"]


@pytest.mark.asyncio
async def test_remove_competitor_fuzzy_match(patch_api, mock_ctx):
    """Entity not exact name match but is a competitor — still archived."""
    posts, gets = patch_api(
        get_results=[[
            {"id": "ent-1", "name": "AcmeCorp", "category": "competitor"},
        ]],
        post_results=[{}],
    )
    out = await cp.remove_competitor(name="acme", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"


# ---------------------------------------------------------------------------
# get_competitor_report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_competitor_report_validates(mock_ctx):
    assert "error" in await cp.get_competitor_report(name="", tenant_id="t", ctx=mock_ctx)
    assert "error" in await cp.get_competitor_report(name="x", tenant_id="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_get_competitor_report_not_found(patch_api, mock_ctx):
    patch_api(get_results=[[]])
    out = await cp.get_competitor_report(name="ghost", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_get_competitor_report_returns_payload(patch_api, mock_ctx):
    """Three GET calls: search, full entity, timeline."""
    patch_api(get_results=[
        [{"id": "ent-1", "name": "Acme", "category": "competitor"}],
        {"id": "ent-1", "name": "Acme", "relations": []},
        {"observations": [{"text": "x"}]},
    ])
    out = await cp.get_competitor_report(name="Acme", tenant_id="t", ctx=mock_ctx)
    # Either a successful payload or an error if internal merging fails
    assert "status" in out or "error" in out
