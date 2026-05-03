"""Tests for src.mcp_tools.memory_continuity.

Five small REST passthrough tools — synthesize_daily/weekly_journal,
get_morning_briefing, expire_behavioral_signals, get_learning_stats.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import memory_continuity as mc


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(mc.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_internal_helper_get_attaches_headers(patch_httpx):
    client = patch_httpx(default_status=200, default_json={"ok": True})
    out = await mc._internal("get", "/api/v1/x", "tenant-1")
    assert out == {"ok": True}
    assert client.calls[0]["method"] == "GET"
    assert client.calls[0]["headers"]["X-Tenant-Id"] == "tenant-1"
    assert "json" not in client.calls[0]


@pytest.mark.asyncio
async def test_internal_helper_post_includes_json_body(patch_httpx):
    client = patch_httpx(default_status=201, default_json={"id": "x"})
    out = await mc._internal("post", "/api/v1/x", "t", {"k": "v"})
    assert out == {"id": "x"}
    assert client.calls[0]["json"] == {"k": "v"}


@pytest.mark.asyncio
async def test_internal_helper_204_returns_status(patch_httpx):
    patch_httpx(default_status=204)
    out = await mc._internal("post", "/x", "t")
    assert out == {"status": "success"}


@pytest.mark.asyncio
async def test_internal_helper_error_returns_error_dict(patch_httpx):
    patch_httpx(default_status=500, default_json={})
    out = await mc._internal("get", "/x", "t")
    assert "error" in out


@pytest.mark.asyncio
async def test_synthesize_daily_journal(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"journal_id": "j-1"})
    out = await mc.synthesize_daily_journal(tenant_id="t", ctx=mock_ctx)
    assert out == {"journal_id": "j-1"}
    assert "synthesize-daily" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_synthesize_weekly_journal(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"journal_id": "j-w"})
    out = await mc.synthesize_weekly_journal(tenant_id="t", ctx=mock_ctx)
    assert out["journal_id"] == "j-w"
    assert "synthesize-weekly" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_morning_briefing_passes_lookback(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"briefing": "..."})
    await mc.get_morning_briefing(days_lookback=14, tenant_id="t", ctx=mock_ctx)
    assert "days_lookback=14" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_expire_behavioral_signals(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"expired": 5})
    out = await mc.expire_behavioral_signals(tenant_id="t", ctx=mock_ctx)
    assert out["expired"] == 5
    assert "behavioral-signals/expire" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_learning_stats_with_default_days(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"stats": []})
    await mc.get_learning_stats(tenant_id="t", ctx=mock_ctx)
    # default days=14 should be in URL
    assert "days=14" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_learning_stats_custom_days(patch_httpx, mock_ctx):
    client = patch_httpx(default_status=200, default_json={"stats": []})
    await mc.get_learning_stats(days=30, tenant_id="t", ctx=mock_ctx)
    assert "days=30" in client.calls[0]["url"]
