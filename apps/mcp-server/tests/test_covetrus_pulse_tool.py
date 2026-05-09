"""Tests for src.mcp_tools.covetrus_pulse — Covetrus Pulse Connect MCP tools.

Covers:
- Tenant + connectivity guards
- Credential extraction (client_id + client_secret + practice_id + environment + location_ids)
- Date-range parsing (1d / 7d / explicit / today)
- HMAC signature is deterministic given inputs (and matches the documented spec)
- OAuth2 token exchange + token caching across calls
- Both auth flows wire correctly (PULSE_AUTH_FLOW=oauth vs hmac)
- Happy paths for all three tools using the mock-Pulse fixtures
- Location filtering (per-call AND credential-allowlist)
- Multi-Site Revenue Sync rollup math (totals_by_location)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict

import pytest

from src.mcp_tools import covetrus_pulse as cp
from tests.fixtures import covetrus_pulse_fixtures as fx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_redis(monkeypatch):
    """Force the cache helpers to behave as no-op so tests stay hermetic."""
    monkeypatch.setattr(cp, "_get_redis", lambda: None)
    yield


@pytest.fixture(autouse=True)
def reset_oauth_cache():
    """Pulse OAuth tokens are cached per-process — reset between tests so a
    stale token doesn't bleed into the next case."""
    cp._oauth_token_cache.clear()
    yield
    cp._oauth_token_cache.clear()


@pytest.fixture
def patch_creds(monkeypatch):
    def _install(creds):
        async def _get(tenant_id):
            return creds

        monkeypatch.setattr(cp, "_get_pulse_credentials", _get)
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
        monkeypatch.setattr(cp.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.fixture
def force_oauth_flow(monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_FLOW", "oauth")
    yield


@pytest.fixture
def force_hmac_flow(monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_FLOW", "hmac")
    yield


# ---------------------------------------------------------------------------
# HMAC signature
# ---------------------------------------------------------------------------


def test_hmac_signature_matches_spec():
    client_id = "demo_client"
    secret = "demo_secret"
    expires = 1_700_000_000
    path = "/v1/patients/pat_1"

    payload = f"{client_id}{expires}{path}".encode("utf-8")
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode("utf-8")

    assert cp._sign_hmac(client_id, secret, expires, path) == expected


def test_build_hmac_params_includes_three_required_fields(monkeypatch):
    monkeypatch.setattr(cp.time, "time", lambda: 1_700_000_000)
    auth = cp._build_hmac_params("c", "s", "/v1/patients/p")
    assert set(auth) == {"api-key", "sig", "expires"}
    assert auth["api-key"] == "c"
    expected_expires = 1_700_000_000 + cp.HMAC_SIG_WINDOW_SECONDS
    assert auth["expires"] == str(expected_expires)
    assert auth["sig"] == cp._sign_hmac("c", "s", expected_expires, "/v1/patients/p")


# ---------------------------------------------------------------------------
# Credential extraction
# ---------------------------------------------------------------------------


def test_extract_credentials_full():
    out = cp._extract_credentials({
        "client_id": "cid",
        "client_secret": "csec",
        "practice_id": "p_42",
        "environment": "sandbox",
        "location_ids": "anaheim,buena_park,mission_viejo",
    })
    assert out["client_id"] == "cid"
    assert out["client_secret"] == "csec"
    assert out["practice_id"] == "p_42"
    assert out["environment"] == "sandbox"
    assert out["location_ids"] == ["anaheim", "buena_park", "mission_viejo"]


def test_extract_credentials_camelcase_alias():
    out = cp._extract_credentials({
        "clientId": "cid",
        "clientSecret": "csec",
        "practiceId": "p_42",
    })
    assert out["client_id"] == "cid"
    assert out["client_secret"] == "csec"
    assert out["practice_id"] == "p_42"
    assert out["environment"] == "prod"  # default
    assert out["location_ids"] == []


def test_extract_credentials_location_ids_as_list():
    out = cp._extract_credentials({
        "client_id": "c",
        "client_secret": "s",
        "location_ids": ["anaheim", "buena_park"],
    })
    assert out["location_ids"] == ["anaheim", "buena_park"]


def test_extract_credentials_returns_none_without_required_fields():
    assert cp._extract_credentials({}) is None
    assert cp._extract_credentials({"client_id": "c"}) is None
    assert cp._extract_credentials({"client_secret": "s"}) is None
    assert cp._extract_credentials(None) is None


# ---------------------------------------------------------------------------
# Auth-flow selection
# ---------------------------------------------------------------------------


def test_auth_flow_default_is_oauth(monkeypatch):
    monkeypatch.delenv("PULSE_AUTH_FLOW", raising=False)
    assert cp._get_auth_flow() == "oauth"


def test_auth_flow_unknown_value_falls_back_to_oauth(monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_FLOW", "weird")
    assert cp._get_auth_flow() == "oauth"


def test_auth_flow_hmac_branch(monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_FLOW", "hmac")
    assert cp._get_auth_flow() == "hmac"


# ---------------------------------------------------------------------------
# Date-range parsing
# ---------------------------------------------------------------------------


def test_parse_date_range_relative():
    start, end = cp._parse_date_range("7d")
    assert start <= end
    # Length should be 7 days (start through end inclusive)
    from datetime import date

    sd = date.fromisoformat(start)
    ed = date.fromisoformat(end)
    assert (ed - sd).days == 6


def test_parse_date_range_explicit():
    start, end = cp._parse_date_range("2026-05-01/2026-05-08")
    assert start == "2026-05-01"
    assert end == "2026-05-08"


def test_parse_date_range_today():
    start, end = cp._parse_date_range("today")
    assert start == end


def test_parse_date_range_default_is_today_when_blank():
    start, end = cp._parse_date_range("")
    assert start == end


# ---------------------------------------------------------------------------
# Tenant + connectivity guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (cp.pulse_get_patient, {"patient_id": "p1"}),
        (cp.pulse_list_appointments, {}),
        (cp.pulse_query_invoices, {}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out
    assert "tenant_id" in out["error"]


@pytest.mark.asyncio
async def test_get_patient_requires_patient_id(patch_creds, mock_ctx):
    patch_creds({"client_id": "c", "client_secret": "s"})
    out = await cp.pulse_get_patient(patient_id="", tenant_id="t", ctx=mock_ctx)
    assert "patient_id" in out["error"]


@pytest.mark.asyncio
async def test_returns_error_when_not_connected(monkeypatch, mock_ctx):
    async def _none(_):
        return None

    monkeypatch.setattr(cp, "_get_pulse_credentials", _none)
    out = await cp.pulse_get_patient(patient_id="p1", tenant_id="t", ctx=mock_ctx)
    assert "Covetrus Pulse not connected" in out["error"]


@pytest.mark.asyncio
async def test_returns_error_when_creds_incomplete(patch_creds, mock_ctx):
    patch_creds({"client_id": "c"})  # missing client_secret
    out = await cp.pulse_list_appointments(tenant_id="t", ctx=mock_ctx)
    assert "Covetrus Pulse not connected" in out["error"]


# ---------------------------------------------------------------------------
# OAuth flow — token fetch + caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_token_is_cached_across_calls(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """A second tool call within the token TTL should NOT re-hit /oauth/token."""
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p_42",
    })

    token_calls = {"count": 0}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            token_calls["count"] += 1
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/patients/" in url:
            return _DummyResponse(200, fx.PATIENT_FULL)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    a = await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx)
    b = await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx, force_refresh=True)

    assert a["status"] == "success"
    assert b["status"] == "success"
    # Two patient fetches but only ONE oauth exchange
    assert token_calls["count"] == 1


@pytest.mark.asyncio
async def test_cache_is_tenant_scoped(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """Critical multi-tenancy guard (PR #330 review Important #2).

    A cache hit on tenant_a's patient lookup must NOT serve tenant_b's
    same-patient_id call. Cache keys are namespaced as
    ``covetrus_pulse:{tenant_id}:{suffix}`` — verify the upstream is
    actually called twice when the only difference is tenant_id.
    """
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    upstream_calls = {"patient": 0}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/patients/" in url:
            upstream_calls["patient"] += 1
            return _DummyResponse(200, fx.PATIENT_FULL)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    # Tenant A primes the cache for patient pat_8472
    a = await cp.pulse_get_patient(
        patient_id="pat_8472", tenant_id="tenant_a", ctx=mock_ctx
    )
    # Same patient_id, different tenant — must hit upstream, NOT cache
    b = await cp.pulse_get_patient(
        patient_id="pat_8472", tenant_id="tenant_b", ctx=mock_ctx
    )

    assert a["status"] == "success"
    assert b["status"] == "success"
    # Two distinct upstream calls — proves the cache key includes tenant_id
    assert upstream_calls["patient"] == 2, (
        "cross-tenant cache leak: same patient_id served from cache "
        "across different tenant_id"
    )


@pytest.mark.asyncio
async def test_oauth_token_failure_surfaces_clean_error(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(401, {"error": "invalid_client"}, text="invalid_client")
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    out = await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert "OAuth token exchange failed" in out["error"]


@pytest.mark.asyncio
async def test_oauth_request_sends_bearer_header(monkeypatch, patch_creds, mock_ctx, force_oauth_flow):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    captured: Dict[str, Any] = {}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        # patient call
        captured["headers"] = kwargs.get("headers")
        captured["params"] = kwargs.get("params")
        return _DummyResponse(200, fx.PATIENT_FULL)

    from tests.conftest import DummyHttpxClient, _DummyResponse

    client = DummyHttpxClient(side_effect=_route, default=_DummyResponse(200, {}))
    monkeypatch.setattr(cp.httpx, "AsyncClient", lambda *a, **kw: client)

    await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx)

    assert captured["headers"]["Authorization"] == "Bearer fake-access-token-abc123"
    # OAuth flow must NOT include HMAC params on the actual data call
    assert "sig" not in (captured.get("params") or {})


# ---------------------------------------------------------------------------
# HMAC flow — request shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hmac_request_sends_sig_params_no_bearer(
    monkeypatch, patch_creds, mock_ctx, force_hmac_flow
):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    captured: Dict[str, Any] = {}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        # In HMAC flow we should NEVER hit /oauth/token
        assert "/oauth/token" not in url, "HMAC flow must not exchange OAuth tokens"
        captured["headers"] = kwargs.get("headers")
        captured["params"] = kwargs.get("params") or {}
        return _DummyResponse(200, fx.PATIENT_FULL)

    from tests.conftest import DummyHttpxClient, _DummyResponse

    client = DummyHttpxClient(side_effect=_route, default=_DummyResponse(200, {}))
    monkeypatch.setattr(cp.httpx, "AsyncClient", lambda *a, **kw: client)

    await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx)

    assert "Authorization" not in captured["headers"]
    assert {"api-key", "sig", "expires"} <= set(captured["params"].keys())
    assert captured["params"]["api-key"] == "cid"


# ---------------------------------------------------------------------------
# Happy paths — pulse_get_patient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_patient_happy(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
        "location_ids": "anaheim,buena_park,mission_viejo",
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/patients/" in url:
            return _DummyResponse(200, fx.PATIENT_FULL)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_get_patient(patient_id="pat_8472", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    p = out["patient"]
    assert p["patient_id"] == "pat_8472"
    assert p["name"] == "Mochi"
    assert "Methimazole" in p["current_medications"][0]["name"]
    assert "chicken" in p["allergies"]
    assert p["location_id"] == "anaheim"


@pytest.mark.asyncio
async def test_get_patient_blocks_disallowed_location(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """If the credential's location_ids allowlist excludes the patient's
    location, the tool MUST refuse to surface the chart."""
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
        "location_ids": "anaheim,buena_park",  # mission_viejo NOT allowed
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/patients/" in url:
            return _DummyResponse(200, fx.PATIENT_DIFFERENT_LOCATION)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_get_patient(patient_id="pat_9999", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert "mission_viejo" in out["error"]


@pytest.mark.asyncio
async def test_get_patient_per_call_location_mismatch(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({"client_id": "c", "client_secret": "s", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/patients/" in url:
            return _DummyResponse(200, fx.PATIENT_FULL)  # location=anaheim
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_get_patient(
        patient_id="pat_8472", tenant_id="t", location_id="buena_park", ctx=mock_ctx
    )
    assert "error" in out
    assert "anaheim" in out["error"]


# ---------------------------------------------------------------------------
# Happy paths — pulse_list_appointments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_appointments_happy(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/appointments" in url:
            return _DummyResponse(200, fx.APPOINTMENTS_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_list_appointments(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 3
    # Normalization preserves the fields agents actually use
    by_id = {a["appointment_id"]: a for a in out["appointments"]}
    assert by_id["appt_1001"]["reason"] == "annual_wellness"
    assert by_id["appt_1003"]["status"] == "scheduled"


@pytest.mark.asyncio
async def test_list_appointments_filters_by_location(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/appointments" in url:
            return _DummyResponse(200, fx.APPOINTMENTS_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_list_appointments(
        tenant_id="t", location_id="anaheim", ctx=mock_ctx
    )
    assert out["count"] == 1
    assert out["appointments"][0]["location_id"] == "anaheim"


@pytest.mark.asyncio
async def test_list_appointments_credential_allowlist_filter(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """When location_id arg is empty, the credential's location_ids allowlist
    should still be applied."""
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
        "location_ids": "anaheim,buena_park",  # excludes mission_viejo
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/appointments" in url:
            return _DummyResponse(200, fx.APPOINTMENTS_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_list_appointments(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 2
    locs = {a["location_id"] for a in out["appointments"]}
    assert locs == {"anaheim", "buena_park"}


# ---------------------------------------------------------------------------
# Happy paths — pulse_query_invoices + per-location rollup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_invoices_happy_with_rollup(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({
        "client_id": "cid", "client_secret": "csec", "practice_id": "p",
    })

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/invoices" in url:
            return _DummyResponse(200, fx.INVOICES_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_query_invoices(tenant_id="t", date_range="1d", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 4

    # Per-location rollup — Multi-Site Revenue Sync depends on this.
    by_loc = {row["location_id"]: row for row in out["totals_by_location"]}
    assert set(by_loc.keys()) == {"anaheim", "buena_park", "mission_viejo"}
    # Anaheim: 482.50 + 215.00 = 697.50, two invoices, both wellness
    assert by_loc["anaheim"]["revenue"] == pytest.approx(697.50)
    assert by_loc["anaheim"]["invoice_count"] == 2
    assert by_loc["anaheim"]["by_service_type"]["wellness"] == pytest.approx(697.50)
    # Buena Park: single dental invoice
    assert by_loc["buena_park"]["revenue"] == pytest.approx(925.00)
    assert by_loc["buena_park"]["by_service_type"]["dental"] == pytest.approx(925.00)
    # Mission Viejo: single surgery invoice
    assert by_loc["mission_viejo"]["revenue"] == pytest.approx(1620.00)
    assert by_loc["mission_viejo"]["by_service_type"]["surgery"] == pytest.approx(1620.00)


@pytest.mark.asyncio
async def test_query_invoices_handles_bare_list_envelope(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """Some Pulse endpoints return a bare JSON list rather than {results: [...]}.
    The flatten helper must accept both shapes."""
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/invoices" in url:
            return _DummyResponse(200, fx.INVOICES_BARE_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_query_invoices(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 4


@pytest.mark.asyncio
async def test_query_invoices_filters_by_location(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/invoices" in url:
            return _DummyResponse(200, fx.INVOICES_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await cp.pulse_query_invoices(
        tenant_id="t", location_id="anaheim", ctx=mock_ctx
    )
    assert out["count"] == 2
    assert all(inv["location_id"] == "anaheim" for inv in out["invoices"])


@pytest.mark.asyncio
async def test_query_invoices_caps_limit(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    """Limit beyond 5000 is capped to 5000 (defensive against runaway queries)."""
    patch_creds({"client_id": "c", "client_secret": "s", "practice_id": "p"})

    captured: Dict[str, Any] = {}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        captured["params"] = kwargs.get("params") or {}
        return _DummyResponse(200, fx.INVOICES_LIST)

    patch_httpx(side_effect=_route)
    await cp.pulse_query_invoices(tenant_id="t", limit=999_999, ctx=mock_ctx)
    assert captured["params"]["limit"] == 5000


# ---------------------------------------------------------------------------
# Upstream error surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upstream_500_surfaces_status_code(patch_creds, patch_httpx, mock_ctx, force_oauth_flow):
    patch_creds({"client_id": "c", "client_secret": "s", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        return _DummyResponse(500, {}, text="upstream meltdown")

    patch_httpx(side_effect=_route)
    out = await cp.pulse_list_appointments(tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert out.get("status_code") == 500
    assert "Pulse API error" in out["error"]
