"""Tests for src.mcp_tools.ads — validation + thin happy-path coverage.

The ads module wraps Meta, Google Ads, and TikTok Ads APIs. We mostly
exercise the early-exit guards and the happy path through Meta tools
where the full chain is shortest.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import ads as ad


@pytest.fixture
def patch_creds(monkeypatch):
    def _install(creds):
        async def _get(tenant_id, integration_name):
            return creds

        monkeypatch.setattr(ad, "_get_ads_credentials", _get)
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
        monkeypatch.setattr(ad.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Required-tenant guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (ad.list_meta_campaigns, {}),
        (ad.get_meta_campaign_insights, {"campaign_id": "x"}),
        (ad.pause_meta_campaign, {"campaign_id": "x"}),
        (ad.list_google_campaigns, {}),
        (ad.get_google_campaign_metrics, {"campaign_id": "x"}),
        (ad.pause_google_campaign, {"campaign_id": "x"}),
        (ad.list_tiktok_campaigns, {}),
        (ad.get_tiktok_campaign_insights, {"campaign_id": "x"}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out


# ---------------------------------------------------------------------------
# Connected-app guards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_meta_campaigns_not_connected(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(ad, "_get_ads_credentials", _none)
    out = await ad.list_meta_campaigns(tenant_id="t", ctx=mock_ctx)
    assert "Meta Ads not connected" in out["error"]


@pytest.mark.asyncio
async def test_list_meta_campaigns_credentials_incomplete(patch_creds, mock_ctx):
    patch_creds({"access_token": "x"})  # missing ad_account_id
    out = await ad.list_meta_campaigns(tenant_id="t", ctx=mock_ctx)
    assert "credentials incomplete" in out["error"]


@pytest.mark.asyncio
async def test_list_meta_campaigns_happy(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "1234"})
    patch_httpx(default_status=200, default_json={
        "data": [{"id": "c1", "name": "Spring", "status": "ACTIVE"}],
    })
    out = await ad.list_meta_campaigns(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 1
    assert out["ad_account_id"] == "act_1234"


@pytest.mark.asyncio
async def test_list_meta_campaigns_with_filter(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1234"})
    client = patch_httpx(default_status=200, default_json={"data": []})
    await ad.list_meta_campaigns(
        status_filter="paused", tenant_id="t", ctx=mock_ctx
    )
    assert client.calls[0]["params"]["effective_status"] == '["PAUSED"]'


@pytest.mark.asyncio
async def test_list_meta_campaigns_token_expired(patch_creds, monkeypatch, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})

    import httpx as real

    class _Resp:
        status_code = 401
        text = "expired"

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

    monkeypatch.setattr(ad.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await ad.list_meta_campaigns(tenant_id="t", ctx=mock_ctx)
    assert "expired" in out["error"]


@pytest.mark.asyncio
async def test_list_meta_campaigns_rate_limited(patch_creds, monkeypatch, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})

    import httpx as real

    class _Resp:
        status_code = 429
        text = ""

        def json(self):
            return {}

        def raise_for_status(self):
            req = real.Request("GET", "http://x")
            raise real.HTTPStatusError("429", request=req, response=real.Response(429, request=req))

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(ad.httpx, "AsyncClient", lambda *a, **kw: _Client())
    out = await ad.list_meta_campaigns(tenant_id="t", ctx=mock_ctx)
    assert "rate limit" in out["error"]


# ---------------------------------------------------------------------------
# get_meta_campaign_insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_meta_insights_validates_campaign_id(mock_ctx):
    out = await ad.get_meta_campaign_insights(
        campaign_id="", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_get_meta_insights_no_data(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})
    patch_httpx(default_status=200, default_json={"data": []})
    out = await ad.get_meta_campaign_insights(
        campaign_id="c-1", date_preset="last_30d",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["metrics"] == {}


@pytest.mark.asyncio
async def test_get_meta_insights_happy(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})
    patch_httpx(default_status=200, default_json={"data": [{
        "impressions": "1000", "clicks": "100", "spend": "50.00",
        "ctr": "10", "cpc": "0.50", "cpp": "1",
        "reach": "500", "frequency": "2",
        "actions": [{"action_type": "lead", "value": "5"}],
    }]})
    out = await ad.get_meta_campaign_insights(
        campaign_id="c-1", tenant_id="t", ctx=mock_ctx,
    )
    assert out["metrics"]["clicks"] == "100"
    assert out["conversions"]["lead"] == "5"


@pytest.mark.asyncio
async def test_get_meta_insights_falls_back_invalid_preset(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})
    client = patch_httpx(default_status=200, default_json={"data": []})
    await ad.get_meta_campaign_insights(
        campaign_id="c-1", date_preset="weird_value",
        tenant_id="t", ctx=mock_ctx,
    )
    # Should fall back to last_7d
    assert client.calls[0]["params"]["date_preset"] == "last_7d"


# ---------------------------------------------------------------------------
# pause_meta_campaign
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_meta_campaign_validates(mock_ctx):
    out = await ad.pause_meta_campaign(
        campaign_id="", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_pause_meta_campaign_happy(patch_creds, patch_httpx, mock_ctx, patch_settings):
    patch_creds({"access_token": "tok", "ad_account_id": "act_1"})
    patch_httpx(default_status=200, default_json={"success": True})
    out = await ad.pause_meta_campaign(
        campaign_id="c-1", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "success"
