"""Tests for src.mcp_tools.scribblevet — ScribbleVet AI-scribe MCP tools.

Covers:
- Tenant + connectivity guards (each tool refuses without tenant_id)
- Credential extraction (camelCase aliases, missing fields)
- Date-range parsing (15m / 1d / 7d / explicit / today)
- OAuth2 token exchange + token caching across calls
- Bearer header is sent on data calls
- Happy paths for all three tools using the mock-ScribbleVet fixtures
- List endpoint drops rows missing note_id (idempotency-key safety)
- soap_text rendering — section headers + diagnoses + medications
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from src.mcp_tools import scribblevet as sv
from tests.fixtures import scribblevet_fixtures as fx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_redis(monkeypatch):
    """Force the cache helpers to behave as no-op so tests stay hermetic."""
    monkeypatch.setattr(sv, "_get_redis", lambda: None)
    yield


@pytest.fixture(autouse=True)
def reset_oauth_cache():
    """ScribbleVet OAuth tokens are cached per-process — reset between
    tests so a stale token doesn't bleed into the next case."""
    sv._oauth_token_cache.clear()
    yield
    sv._oauth_token_cache.clear()


@pytest.fixture
def patch_creds(monkeypatch):
    def _install(creds):
        async def _get(tenant_id):
            return creds

        monkeypatch.setattr(sv, "_get_scribblevet_credentials", _get)
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
        monkeypatch.setattr(sv.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


# ---------------------------------------------------------------------------
# Credential extraction
# ---------------------------------------------------------------------------


def test_extract_credentials_full():
    out = sv._extract_credentials({
        "client_id": "cid",
        "client_secret": "csec",
        "practice_id": "p_42",
        "environment": "sandbox",
    })
    assert out["client_id"] == "cid"
    assert out["client_secret"] == "csec"
    assert out["practice_id"] == "p_42"
    assert out["environment"] == "sandbox"


def test_extract_credentials_camelcase_alias():
    out = sv._extract_credentials({
        "clientId": "cid",
        "clientSecret": "csec",
        "practiceId": "p_42",
    })
    assert out["client_id"] == "cid"
    assert out["client_secret"] == "csec"
    assert out["practice_id"] == "p_42"
    assert out["environment"] == "prod"  # default


def test_extract_credentials_returns_none_without_required_fields():
    assert sv._extract_credentials({}) is None
    assert sv._extract_credentials({"client_id": "c"}) is None
    assert sv._extract_credentials({"client_secret": "s"}) is None
    assert sv._extract_credentials(None) is None


# ---------------------------------------------------------------------------
# Date-range parsing
# ---------------------------------------------------------------------------


def test_parse_date_range_minutes():
    start, end = sv._parse_date_range("15m")
    # ISO-8601 strings, end > start
    assert start < end


def test_parse_date_range_days():
    start, end = sv._parse_date_range("7d")
    assert start < end


def test_parse_date_range_explicit():
    start, end = sv._parse_date_range("2026-05-01/2026-05-08")
    assert start == "2026-05-01"
    assert end == "2026-05-08"


def test_parse_date_range_today_returns_start_of_day_to_now():
    start, end = sv._parse_date_range("today")
    assert start < end
    # start should be 00:00:00 of today (UTC)
    assert "T00:00:00" in start


def test_parse_date_range_default_is_today_when_blank():
    start, end = sv._parse_date_range("")
    assert start < end


# ---------------------------------------------------------------------------
# Tenant + connectivity guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,kwargs",
    [
        (sv.scribblevet_list_recent_notes, {}),
        (sv.scribblevet_get_note, {"note_id": "n1"}),
        (sv.scribblevet_search, {"query": "limp"}),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_requires_tenant(tool, kwargs, mock_ctx):
    out = await tool(tenant_id="", ctx=mock_ctx, **kwargs)
    assert "error" in out
    assert "tenant_id" in out["error"]


@pytest.mark.asyncio
async def test_get_note_requires_note_id(patch_creds, mock_ctx):
    patch_creds({"client_id": "c", "client_secret": "s"})
    out = await sv.scribblevet_get_note(note_id="", tenant_id="t", ctx=mock_ctx)
    assert "note_id" in out["error"]


@pytest.mark.asyncio
async def test_search_requires_query(patch_creds, mock_ctx):
    patch_creds({"client_id": "c", "client_secret": "s"})
    out = await sv.scribblevet_search(query="", tenant_id="t", ctx=mock_ctx)
    assert "query" in out["error"]


@pytest.mark.asyncio
async def test_returns_error_when_not_connected(monkeypatch, mock_ctx):
    async def _none(_):
        return None

    monkeypatch.setattr(sv, "_get_scribblevet_credentials", _none)
    out = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert "ScribbleVet not connected" in out["error"]


@pytest.mark.asyncio
async def test_returns_error_when_creds_incomplete(patch_creds, mock_ctx):
    patch_creds({"client_id": "c"})  # missing client_secret
    out = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert "ScribbleVet not connected" in out["error"]


# ---------------------------------------------------------------------------
# OAuth flow — token fetch + caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_token_is_cached_across_calls(patch_creds, patch_httpx, mock_ctx):
    """A second tool call within the token TTL should NOT re-hit /oauth/token."""
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p_42"})

    token_calls = {"count": 0}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            token_calls["count"] += 1
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes" in url:
            return _DummyResponse(200, fx.NOTES_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    a = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    b = await sv.scribblevet_list_recent_notes(
        tenant_id="t", ctx=mock_ctx, force_refresh=True
    )

    assert a["status"] == "success"
    assert b["status"] == "success"
    assert token_calls["count"] == 1


@pytest.mark.asyncio
async def test_oauth_token_failure_surfaces_clean_error(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(401, {"error": "invalid_client"}, text="invalid_client")
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    out = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert "OAuth token exchange failed" in out["error"]


@pytest.mark.asyncio
async def test_request_sends_bearer_header(monkeypatch, patch_creds, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    captured: Dict[str, Any] = {}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["params"] = kwargs.get("params")
        return _DummyResponse(200, fx.NOTES_LIST)

    from tests.conftest import DummyHttpxClient, _DummyResponse

    client = DummyHttpxClient(side_effect=_route, default=_DummyResponse(200, {}))
    monkeypatch.setattr(sv.httpx, "AsyncClient", lambda *a, **kw: client)

    await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)

    assert captured["headers"]["Authorization"] == "Bearer fake-scribblevet-token-xyz789"
    # OAuth flow must NOT include HMAC params on data calls
    assert "sig" not in (captured.get("params") or {})


# ---------------------------------------------------------------------------
# Happy paths — scribblevet_list_recent_notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recent_notes_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes" in url:
            return _DummyResponse(200, fx.NOTES_LIST)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)

    assert out["status"] == "success"
    # 3 rows in fixture, but the row missing note_id is dropped → 2 results
    assert out["count"] == 2
    assert {n["note_id"] for n in out["notes"]} == {"sv_note_1001", "sv_note_1002"}
    # Check normalization picked up DVM + patient fields
    note = next(n for n in out["notes"] if n["note_id"] == "sv_note_1001")
    assert note["dvm_name"] == "Dr. Angelo Castillo"
    assert note["patient_name"] == "Mochi"
    assert note["client_name"] == "Maria Lopez"


@pytest.mark.asyncio
async def test_list_recent_notes_handles_bare_list(patch_creds, patch_httpx, mock_ctx):
    """Some upstream endpoints skip the {results: ...} envelope."""
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes" in url:
            return _DummyResponse(200, fx.NOTES_LIST_BARE)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 2


# ---------------------------------------------------------------------------
# Happy paths — scribblevet_get_note + soap_text rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_note_happy_with_soap_text(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec", "practice_id": "p"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes/sv_note_1001" in url:
            return _DummyResponse(200, fx.NOTE_FULL)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await sv.scribblevet_get_note(
        note_id="sv_note_1001", tenant_id="t", ctx=mock_ctx
    )

    assert out["status"] == "success"
    assert out["note"]["note_id"] == "sv_note_1001"
    assert out["note"]["patient_name"] == "Mochi"
    assert out["note"]["dvm_name"] == "Dr. Angelo Castillo"

    # soap_text should include each section header + diagnoses + medications.
    soap = out["soap_text"]
    assert "S (Subjective)" in soap
    assert "O (Objective)" in soap
    assert "A (Assessment)" in soap
    assert "P (Plan)" in soap
    assert "Hyperthyroidism" in soap
    assert "Methimazole" in soap
    # Header bits should be there too.
    assert "Mochi" in soap
    assert "Dr. Angelo Castillo" in soap


@pytest.mark.asyncio
async def test_get_note_unexpected_payload(patch_creds, patch_httpx, mock_ctx):
    """If upstream returns 200 but the payload isn't note-shaped, surface a
    clean error rather than crashing."""
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes/" in url:
            return _DummyResponse(200, {"unrelated": "payload"})
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await sv.scribblevet_get_note(note_id="missing", tenant_id="t", ctx=mock_ctx)
    assert "error" in out
    assert "note not found" in out["error"]


@pytest.mark.asyncio
async def test_get_note_multi_pet_carries_additional_pets(
    patch_creds, patch_httpx, mock_ctx
):
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes/sv_note_2002" in url:
            return _DummyResponse(200, fx.NOTE_MULTI_PET)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)
    out = await sv.scribblevet_get_note(
        note_id="sv_note_2002", tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "success"
    assert len(out["note"]["additional_pets"]) == 1
    assert out["note"]["additional_pets"][0]["patient_name"] == "Cream"


# ---------------------------------------------------------------------------
# Happy paths — scribblevet_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_happy(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes/search" in url:
            assert method == "POST"
            # Search payload sent in JSON body
            sent = kwargs.get("json") or {}
            assert sent.get("query") == "limp"
            return _DummyResponse(200, fx.NOTES_SEARCH)
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    out = await sv.scribblevet_search(query="limp", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 2
    assert {m["note_id"] for m in out["matches"]} == {"sv_note_0801", "sv_note_0901"}
    # All matches are for the same patient — useful for idempotency
    assert all(m["patient_name"] == "Bella" for m in out["matches"])


@pytest.mark.asyncio
async def test_search_passes_patient_filter(patch_creds, patch_httpx, mock_ctx):
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    captured_body: Dict[str, Any] = {}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        if "/v1/notes/search" in url:
            captured_body.update(kwargs.get("json") or {})
            return _DummyResponse(200, {"matches": []})
        return _DummyResponse(200, {})

    patch_httpx(side_effect=_route)

    out = await sv.scribblevet_search(
        query="vomiting", tenant_id="t", patient_id="pat_5500", ctx=mock_ctx
    )
    assert out["status"] == "success"
    assert captured_body.get("patient_id") == "pat_5500"


# ---------------------------------------------------------------------------
# Cache hit short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recent_notes_uses_cache_on_second_call(
    monkeypatch, patch_creds, patch_httpx, mock_ctx
):
    """When _cache_get returns a value, the upstream is not hit."""
    patch_creds({"client_id": "cid", "client_secret": "csec"})

    upstream_hits = {"n": 0}

    def _route(method, url, kwargs):
        from tests.conftest import _DummyResponse

        upstream_hits["n"] += 1
        if "/oauth/token" in url:
            return _DummyResponse(200, fx.OAUTH_TOKEN_RESPONSE)
        return _DummyResponse(200, fx.NOTES_LIST)

    patch_httpx(side_effect=_route)

    # First call: pretend cache miss → upstream hit
    monkeypatch.setattr(sv, "_cache_get", lambda key: None)
    monkeypatch.setattr(sv, "_cache_set", lambda *a, **kw: None)
    a = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert a["status"] == "success"
    a_hits = upstream_hits["n"]
    assert a_hits >= 1  # at least the data call (oauth may or may not have been needed)

    # Second call: pretend cache hit → upstream NOT hit
    cached_payload = {"status": "success", "notes": [], "count": 0}
    monkeypatch.setattr(sv, "_cache_get", lambda key: dict(cached_payload))
    b = await sv.scribblevet_list_recent_notes(tenant_id="t", ctx=mock_ctx)
    assert b["status"] == "success"
    assert b["from_cache"] is True
    # Upstream count unchanged from after first call
    assert upstream_hits["n"] == a_hits


# ---------------------------------------------------------------------------
# soap_text rendering — empty-section behavior
# ---------------------------------------------------------------------------


def test_build_soap_text_skips_empty_sections():
    note = {
        "patient_name": "Bella",
        "visit_date": "2026-05-09",
        "subjective": "history",
        "objective": "",
        "assessment": "  ",
        "plan": "treatment",
    }
    text = sv._build_soap_text(note)
    assert "S (Subjective)" in text
    assert "P (Plan)" in text
    # Empty/whitespace sections should be skipped
    assert "O (Objective)" not in text
    assert "A (Assessment)" not in text


def test_build_soap_text_handles_diagnoses_and_meds_as_dicts():
    note = {
        "patient_name": "Mochi",
        "diagnoses": [{"name": "Hyperthyroidism"}, {"description": "Mild dental disease"}],
        "medications": [{"name": "Methimazole", "dose": "2.5mg PO BID"}],
    }
    text = sv._build_soap_text(note)
    assert "Diagnoses: Hyperthyroidism; Mild dental disease" in text
    assert "Methimazole 2.5mg PO BID" in text
