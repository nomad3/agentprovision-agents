"""Tests for src.mcp_tools.brightlocal — BrightLocal SEO MCP tools.

Covers:
- tenant guard
- not-connected guard (no creds in vault)
- credential extraction (api_key + api_secret + account_id)
- signature generation matches the BrightLocal HMAC-SHA1 spec
- happy paths for each of the 4 tools using DummyHttpxClient
- rank-changes diff math (gain vs loss, min_delta filter)
- competitor degradation when the API tier rejects the include flag
- redis cache short-circuit (force_refresh=True bypasses)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict

import pytest

from src.mcp_tools import brightlocal as bl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_redis(monkeypatch):
    """Force the cache helpers to behave as no-op so tests stay hermetic."""
    monkeypatch.setattr(bl, "_get_redis", lambda: None)
    yield


@pytest.fixture
def patch_creds(monkeypatch):
    def _install(creds):
        async def _get(tenant_id):
            return creds

        monkeypatch.setattr(bl, "_get_brightlocal_credentials", _get)
        return creds

    return _install


@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None, responses=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
            responses=responses,
        )
        monkeypatch.setattr(bl.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


def test_sign_request_matches_official_php_helper():
    """Reproduce the spec exactly: base64(hmac_sha1(api_key + expires, secret))."""
    api_key = "demo_key"
    secret = "demo_secret"
    expires_ts = 1_700_000_000

    expected_payload = f"{api_key}{expires_ts}".encode("utf-8")
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), expected_payload, hashlib.sha1).digest()
    ).decode("utf-8")

    assert bl._sign_request(api_key, secret, expires_ts) == expected


def test_build_auth_params_includes_three_required_fields(monkeypatch):
    monkeypatch.setattr(bl.time, "time", lambda: 1_700_000_000)
    auth = bl._build_auth_params("k", "s")
    assert set(auth) == {"api-key", "sig", "expires"}
    assert auth["api-key"] == "k"
    # expires_ts is now + window; sig is deterministic given inputs
    expected_expires = 1_700_000_000 + bl.SIG_EXPIRES_WINDOW_SECONDS
    assert auth["expires"] == str(expected_expires)
    assert auth["sig"] == bl._sign_request("k", "s", expected_expires)


# ---------------------------------------------------------------------------
# Credential extraction
# ---------------------------------------------------------------------------


def test_extract_credentials_full():
    out = bl._extract_credentials({"api_key": "k", "api_secret": "s", "account_id": "42"})
    assert out == {"api_key": "k", "api_secret": "s", "account_id": "42"}


def test_extract_credentials_falls_back_to_api_key_when_secret_missing():
    out = bl._extract_credentials({"api_key": "k"})
    # Trial-key fallback: secret == key
    assert out["api_key"] == "k"
    assert out["api_secret"] == "k"
    assert out["account_id"] == ""


def test_extract_credentials_supports_camelcase_alias():
    out = bl._extract_credentials({"apiKey": "k", "secret": "s"})
    assert out["api_key"] == "k"
    assert out["api_secret"] == "s"


def test_extract_credentials_returns_none_without_api_key():
    assert bl._extract_credentials({}) is None
    assert bl._extract_credentials({"api_secret": "s"}) is None


# ---------------------------------------------------------------------------
# Tenant + connectivity guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (bl.brightlocal_list_keywords, {}),
        (bl.brightlocal_get_rankings, {}),
        (bl.brightlocal_rank_changes, {}),
        (bl.brightlocal_competitor_check, {}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out
    assert "tenant_id" in out["error"]


@pytest.mark.asyncio
async def test_list_keywords_returns_error_when_not_connected(monkeypatch, mock_ctx):
    async def _none(_):
        return None

    monkeypatch.setattr(bl, "_get_brightlocal_credentials", _none)
    out = await bl.brightlocal_list_keywords(tenant_id="t", ctx=mock_ctx)
    assert "BrightLocal not connected" in out["error"]


@pytest.mark.asyncio
async def test_rankings_returns_error_when_creds_incomplete(patch_creds, mock_ctx):
    patch_creds({})  # vault returned an empty dict
    out = await bl.brightlocal_get_rankings(tenant_id="t", ctx=mock_ctx)
    assert "BrightLocal not connected" in out["error"]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keywords_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    def _route(method, url, kwargs):
        if "/get-all" in url:
            from tests.conftest import _DummyResponse

            return _DummyResponse(
                200,
                {"success": True, "response": [{"campaign_id": "c1"}, {"campaign_id": "c2"}]},
            )
        if "/lsrc/get" in url:
            from tests.conftest import _DummyResponse

            return _DummyResponse(
                200,
                {
                    "success": True,
                    "response": {
                        "results": [
                            {"keyword": "vet near me", "search_engine": "google"},
                            {"keyword": "cardiology vet", "search_engine": "google"},
                        ]
                    },
                },
            )
        return None

    patch_httpx(side_effect=_route)
    out = await bl.brightlocal_list_keywords(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    # 2 campaigns × 2 keywords each
    assert out["count"] == 4
    assert sorted(out["campaigns"]) == ["c1", "c2"]
    assert all("keyword" in row for row in out["keywords"])


@pytest.mark.asyncio
async def test_get_rankings_filters_by_keyword(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/get-all" in url:
            return _DummyResponse(200, {"success": True, "response": [{"campaign_id": "c1"}]})
        if "/results/get" in url:
            return _DummyResponse(
                200,
                {
                    "success": True,
                    "response": {
                        "results": [
                            {"keyword": "vet near me", "rank": 4, "url": "x"},
                            {"keyword": "dog grooming", "rank": 2, "url": "y"},
                        ]
                    },
                },
            )
        return None

    patch_httpx(side_effect=_route)

    # No filter → both rows
    full = await bl.brightlocal_get_rankings(tenant_id="t", ctx=mock_ctx)
    assert full["count"] == 2

    # Filter → only the matching row
    filtered = await bl.brightlocal_get_rankings(
        tenant_id="t", ctx=mock_ctx, keyword="vet", force_refresh=True
    )
    assert filtered["count"] == 1
    assert filtered["rankings"][0]["keyword"] == "vet near me"


@pytest.mark.asyncio
async def test_rank_changes_computes_deltas(monkeypatch, patch_creds, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    async def _stub_rankings(**kwargs):
        return {
            "status": "success",
            "rankings": [
                # Improved by 3 (was 8, now 5)
                {"keyword": "vet near me", "position": 5, "previous_position": 8, "url": "/a"},
                # Dropped by 4 (was 3, now 7)
                {"keyword": "cardio vet", "position": 7, "previous_position": 3, "url": "/b"},
                # No change (filtered out by min_delta)
                {"keyword": "stable kw", "position": 2, "previous_position": 2, "url": "/c"},
                # No history → ignored
                {"keyword": "new kw", "position": 1, "url": "/d"},
            ],
            "from_cache": False,
        }

    monkeypatch.setattr(bl, "brightlocal_get_rankings", _stub_rankings)

    out = await bl.brightlocal_rank_changes(tenant_id="t", ctx=mock_ctx, min_delta=1)
    assert out["status"] == "success"
    assert out["summary"]["total_changes"] == 2
    assert out["summary"]["losses"] == 1
    assert out["summary"]["gains"] == 1
    # biggest_losses sorted with most negative delta first
    assert out["biggest_losses"][0]["keyword"] == "cardio vet"
    assert out["biggest_losses"][0]["delta"] == -4
    assert out["biggest_gains"][0]["keyword"] == "vet near me"
    assert out["biggest_gains"][0]["delta"] == 3


@pytest.mark.asyncio
async def test_rank_changes_min_delta_filter(monkeypatch, patch_creds, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    async def _stub_rankings(**kwargs):
        return {
            "status": "success",
            "rankings": [
                {"keyword": "small move", "position": 5, "previous_position": 6, "url": "/x"},
                {"keyword": "big drop", "position": 12, "previous_position": 5, "url": "/y"},
            ],
            "from_cache": False,
        }

    monkeypatch.setattr(bl, "brightlocal_get_rankings", _stub_rankings)

    out = await bl.brightlocal_rank_changes(tenant_id="t", ctx=mock_ctx, min_delta=3)
    assert out["summary"]["total_changes"] == 1
    assert out["changes"][0]["keyword"] == "big drop"


@pytest.mark.asyncio
async def test_competitor_check_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/get-all" in url:
            return _DummyResponse(200, {"success": True, "response": [{"campaign_id": "c1"}]})
        if "/results/get" in url:
            return _DummyResponse(
                200,
                {
                    "success": True,
                    "response": {
                        "results": [
                            {
                                "keyword": "vet near me",
                                "rank": 4,
                                "competitors": [
                                    {"url": "https://rival-vet.com", "rank": 2},
                                    {"url": "https://other-vet.com", "rank": 7},
                                ],
                            }
                        ]
                    },
                },
            )
        return None

    patch_httpx(side_effect=_route)
    out = await bl.brightlocal_competitor_check(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 2
    urls = {row["competitor_url"] for row in out["competitors"]}
    assert "https://rival-vet.com" in urls


@pytest.mark.asyncio
async def test_competitor_check_filters_by_competitor_url(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/get-all" in url:
            return _DummyResponse(200, {"success": True, "response": [{"campaign_id": "c1"}]})
        if "/results/get" in url:
            return _DummyResponse(
                200,
                {
                    "success": True,
                    "response": {
                        "results": [
                            {
                                "keyword": "kw",
                                "competitors": [
                                    {"url": "https://rival-vet.com", "rank": 2},
                                    {"url": "https://other-vet.com", "rank": 7},
                                ],
                            }
                        ]
                    },
                },
            )
        return None

    patch_httpx(side_effect=_route)
    out = await bl.brightlocal_competitor_check(
        tenant_id="t", ctx=mock_ctx, competitor_url="rival-vet"
    )
    assert out["count"] == 1
    assert out["competitors"][0]["competitor_url"] == "https://rival-vet.com"


@pytest.mark.asyncio
async def test_competitor_check_degrades_on_403(patch_creds, patch_httpx, mock_ctx):
    """Lower BrightLocal API tiers reject competitor data with 403 — the tool
    should return ``status=no_competitor_data`` so the workflow still runs."""
    patch_creds({"api_key": "k", "api_secret": "s"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/get-all" in url:
            return _DummyResponse(200, {"success": True, "response": [{"campaign_id": "c1"}]})
        if "/results/get" in url:
            return _DummyResponse(403, {"success": False, "errors": "tier"})
        return None

    patch_httpx(side_effect=_route)
    out = await bl.brightlocal_competitor_check(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "no_competitor_data"
    assert out["count"] == 0


# ---------------------------------------------------------------------------
# Cache short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_without_hitting_brightlocal(monkeypatch, patch_creds, mock_ctx):
    """If the cache layer reports a hit, the tool should return immediately."""
    patch_creds({"api_key": "k", "api_secret": "s"})

    cached_payload = {
        "status": "success",
        "keywords": [{"keyword": "from cache"}],
        "count": 1,
        "campaigns": ["c1"],
        "from_cache": False,
    }
    monkeypatch.setattr(bl, "_cache_get", lambda key: cached_payload.copy())

    # If we hit BrightLocal we'd get an unexpected exception — make sure that
    # path is never taken.
    def _explode(*a, **kw):
        raise AssertionError("brightlocal API should not be called on a cache hit")

    monkeypatch.setattr(bl.httpx, "AsyncClient", _explode)

    out = await bl.brightlocal_list_keywords(tenant_id="t", ctx=mock_ctx)
    assert out["from_cache"] is True
    assert out["count"] == 1


@pytest.mark.asyncio
async def test_force_refresh_skips_cache(monkeypatch, patch_creds, patch_httpx, mock_ctx):
    patch_creds({"api_key": "k", "api_secret": "s"})

    monkeypatch.setattr(
        bl, "_cache_get", lambda key: {"status": "success", "keywords": [], "count": 0}
    )

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/get-all" in url:
            return _DummyResponse(200, {"success": True, "response": []})
        return None

    patch_httpx(side_effect=_route)
    out = await bl.brightlocal_list_keywords(
        tenant_id="t", ctx=mock_ctx, force_refresh=True
    )
    # force_refresh ignores cache and goes upstream — empty campaign list returned
    assert out["from_cache"] is False
    assert out["count"] == 0


# ---------------------------------------------------------------------------
# Result normalization helpers
# ---------------------------------------------------------------------------


def test_flatten_results_payload_handles_three_shapes():
    # Shape 1: top-level results list
    rows = bl._flatten_results_payload({"results": [{"a": 1}, {"a": 2}]})
    assert len(rows) == 2

    # Shape 2: list of dicts each with results
    rows = bl._flatten_results_payload(
        [{"results": [{"a": 1}]}, {"results": [{"a": 2}, {"a": 3}]}]
    )
    assert len(rows) == 3

    # Shape 3: bare dict gets wrapped
    rows = bl._flatten_results_payload({"keyword": "x"})
    assert len(rows) == 1
