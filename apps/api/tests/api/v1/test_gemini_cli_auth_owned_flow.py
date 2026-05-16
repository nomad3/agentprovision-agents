"""Tests for the api-owned PKCE OAuth flow that replaces the gemini
subprocess paste-code dance.

The previous flow spawned `gemini` in a tenant-scoped temp HOME and
forwarded the user-pasted authorization code into the subprocess's
pty. That had four independent failure modes that all collapsed to
exitCode 41 / FatalAuthenticationError. The replacement owns the
OAuth dance directly: `/start` mints a PKCE-backed authUrl,
`/submit-code` exchanges the code at `oauth2.googleapis.com/token`
ourselves.

Coverage:
  * Happy path — `/submit-code` with a healthy Google response writes
    three vault rows (oauth_creds, oauth_token, refresh_token) and
    flips status → 'connected'.
  * Sad path — Google returns `invalid_grant` (typical expired/used
    authorization code). No vault row written, status='failed' with a
    sanitised user-facing message.
  * Idempotency — calling `/submit-code` a second time after success
    is a no-op (returns 'connected', does NOT re-call Google, does
    NOT re-write rows).

Design: docs/plans/2026-05-16-gemini-cli-oauth-exitcode-41.md
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import httpx
import pytest

pytest.importorskip("fastapi")

from app.api.v1 import gemini_cli_auth as ga


# ── Helpers ───────────────────────────────────────────────────────────────


_TENANT = "11111111-1111-1111-1111-111111111111"

# Test fixture: pin the OAuth client used by _load_gemini_oauth_client
# so tests don't depend on a `@google/gemini-cli` install on the test
# host. The real loader prefers env vars over bundle scanning. Values
# are shape-realistic but bogus.
_TEST_CLIENT_ID = "111111111111-testclientid.apps.googleusercontent.com"
_TEST_CLIENT_SECRET = "GOCSPX-testsecret-" + "x" * 28


@pytest.fixture(autouse=True)
def _pin_oauth_client(monkeypatch):
    """All tests in this module pin the gemini-cli OAuth client to
    deterministic test values. The loader is lru_cached so we also
    need to bust the cache between tests."""
    monkeypatch.setenv("GEMINI_OAUTH_CLIENT_ID", _TEST_CLIENT_ID)
    monkeypatch.setenv("GEMINI_OAUTH_CLIENT_SECRET", _TEST_CLIENT_SECRET)
    ga._load_gemini_oauth_client.cache_clear()
    yield
    ga._load_gemini_oauth_client.cache_clear()


def _fresh_manager():
    """Return a new manager so test ordering doesn't leak state."""
    return ga.GeminiAuthManager()


def _stub_db(monkeypatch, captured: list):
    """Wire SessionLocal + store_credential so we can assert on writes
    without touching a real database. Returns the chain object so tests
    can assert which config branch was hit."""
    chain = MagicMock()
    chain.filter.return_value = chain
    cfg = MagicMock()
    cfg.id = uuid.uuid4()
    cfg.enabled = True
    chain.first.return_value = cfg
    db = MagicMock()
    db.query.return_value = chain
    monkeypatch.setattr(ga, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        ga,
        "store_credential",
        lambda db, **kw: captured.append(kw),
    )
    return chain, cfg


# ── PKCE + URL: pure helpers ─────────────────────────────────────────────


def test_pkce_challenge_is_s256_base64url_nopad():
    """RFC 7636: code_challenge = base64url(SHA256(verifier)), no padding."""
    # Test vector from the RFC appendix:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert ga._pkce_challenge(verifier) == expected


def test_build_auth_url_includes_pkce_state_consent_and_gemini_client_id():
    """The authUrl must carry every parameter gemini-cli's own
    implementation embeds. Missing any of these breaks the token
    exchange downstream (codeVerifier mismatch, no refresh_token, etc).
    """
    url = ga._build_auth_url("CHAL_VAL", "STATE_VAL")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    # The client_id loaded at runtime (env override in tests, bundle
    # scan in prod) — refresh_token must work against the cloudcode-pa
    # API the code-worker hits later, so we must use the same client_id
    # gemini-cli embeds.
    expected_id, _ = ga._load_gemini_oauth_client()
    assert expected_id in url
    # Same redirect_uri or Google rejects the request (no localhost).
    assert "redirect_uri=https%3A%2F%2Fcodeassist.google.com%2Fauthcode" in url
    assert "code_challenge=CHAL_VAL" in url
    assert "code_challenge_method=S256" in url
    assert "state=STATE_VAL" in url
    assert "access_type=offline" in url
    # prompt=consent forces Google to issue a refresh_token even if
    # the user has previously granted consent for this client.
    assert "prompt=consent" in url


def test_build_oauth_creds_blob_matches_gemini_schema():
    """The persisted blob must match the shape gemini-cli reads from
    `~/.gemini/oauth_creds.json` — anything else and the code-worker
    fails to refresh during the next chat turn."""
    tokens = {
        "access_token": "ya29.test",
        "refresh_token": "1//refresh-test",
        "scope": "scope-1 scope-2",
        "token_type": "Bearer",
        "expires_in": 3599,
        "id_token": "eyJ.id.token",
    }
    blob = ga._build_oauth_creds_blob(tokens)
    assert blob["access_token"] == "ya29.test"
    assert blob["refresh_token"] == "1//refresh-test"
    assert blob["scope"] == "scope-1 scope-2"
    assert blob["token_type"] == "Bearer"
    assert blob["id_token"] == "eyJ.id.token"
    # expiry_date is ms-since-epoch (gemini's google-auth-library shape).
    assert isinstance(blob["expiry_date"], int)
    assert blob["expiry_date"] > 1_700_000_000_000  # > 2023 in ms


# ── start_login: state plumbing ──────────────────────────────────────────


def test_start_login_creates_state_with_verification_url():
    mgr = _fresh_manager()
    state = mgr.start_login(_TENANT)
    assert state.tenant_id == _TENANT
    assert state.status == "pending"
    assert state.verification_url is not None
    assert state.verification_url.startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )
    assert state.code_verifier and len(state.code_verifier) >= 43
    assert state.state_token and len(state.state_token) >= 32


def test_start_login_replaces_existing_state_for_same_tenant():
    """Re-clicking Connect must hand back a fresh code_verifier — the
    OLD authorization code (if any) would not match a new verifier."""
    mgr = _fresh_manager()
    first = mgr.start_login(_TENANT)
    second = mgr.start_login(_TENANT)
    assert first.code_verifier != second.code_verifier
    assert first.login_id != second.login_id
    # Lookup returns the most recent state.
    assert mgr.get_state(_TENANT).login_id == second.login_id


# ── submit_code: happy path ──────────────────────────────────────────────


def test_submit_code_happy_path_writes_three_vault_rows(monkeypatch):
    """The contract that the code-worker depends on: three vault rows
    keyed by `oauth_creds`, `oauth_token`, `refresh_token`. The blob
    row holds the full JSON; the per-field rows hold raw strings for
    convenience consumers."""
    mgr = _fresh_manager()
    state = mgr.start_login(_TENANT)

    captured_writes: list = []
    _stub_db(monkeypatch, captured_writes)

    def fake_exchange(code, verifier):
        assert code == "AUTH_CODE_FROM_USER"
        assert verifier == state.code_verifier
        return {
            "access_token": "ya29.access",
            "refresh_token": "1//refresh",
            "scope": ga.GEMINI_OAUTH_SCOPE,
            "token_type": "Bearer",
            "expires_in": 3599,
        }

    monkeypatch.setattr(ga, "_exchange_code_for_tokens", fake_exchange)

    result = mgr.submit_code(_TENANT, "  AUTH_CODE_FROM_USER  ")
    assert result is state
    assert result.status == "connected"
    assert result.connected is True
    assert result.error is None
    assert result.completed_at is not None

    keys = [w["credential_key"] for w in captured_writes]
    assert keys == ["oauth_creds", "oauth_token", "refresh_token"]
    # The oauth_creds row holds a JSON blob, NOT raw tokens.
    oauth_creds_row = captured_writes[0]
    blob = json.loads(oauth_creds_row["plaintext_value"])
    assert blob["access_token"] == "ya29.access"
    assert blob["refresh_token"] == "1//refresh"
    # All three rows MUST be type 'oauth_token' — the executor reader
    # filters on type, not just key.
    for w in captured_writes:
        assert w["credential_type"] == "oauth_token"


def test_submit_code_rejects_response_without_refresh_token(monkeypatch):
    """Without refresh_token the credential dies within ~1h. Don't
    persist; surface a directly actionable error pointing at
    myaccount.google.com/permissions (the canonical fix)."""
    mgr = _fresh_manager()
    mgr.start_login(_TENANT)

    captured_writes: list = []
    _stub_db(monkeypatch, captured_writes)

    monkeypatch.setattr(
        ga,
        "_exchange_code_for_tokens",
        lambda code, verifier: {
            "access_token": "ya29.access",
            # refresh_token deliberately missing
            "expires_in": 3599,
        },
    )

    result = mgr.submit_code(_TENANT, "any-code")
    assert result.status == "failed"
    assert result.connected is False
    assert "refresh_token" in (result.error or "")
    # Zero vault writes when the response is unusable.
    assert captured_writes == []


# ── submit_code: sad path (Google rejects code) ──────────────────────────


def test_submit_code_translates_invalid_grant_to_user_message(monkeypatch):
    """Google's `invalid_grant` is the typical expired/used-code
    failure mode. The user message must be actionable; the raw Google
    response body must NOT leak through (potential PII / code echo)."""
    mgr = _fresh_manager()
    mgr.start_login(_TENANT)

    captured_writes: list = []
    _stub_db(monkeypatch, captured_writes)

    def raising_exchange(code, verifier):
        raise ga._OAuthExchangeError(
            safe_message="400 invalid_grant: Bad Request",
            user_message=(
                "Google rejected the authorization code (it may have "
                "expired or already been used). Click Connect to start "
                "a new flow."
            ),
        )

    monkeypatch.setattr(ga, "_exchange_code_for_tokens", raising_exchange)

    result = mgr.submit_code(_TENANT, "expired-code")
    assert result.status == "failed"
    assert result.connected is False
    assert "authorization code" in (result.error or "").lower()
    # Raw Google body MUST NOT appear in user-facing error.
    assert "400" not in (result.error or "")
    assert captured_writes == []


def test_submit_code_handles_empty_code_without_calling_google(monkeypatch):
    """Empty/whitespace input is a frontend bug, not a Google call.
    Fail fast and locally so we don't burn against Google's quota."""
    mgr = _fresh_manager()
    mgr.start_login(_TENANT)

    calls = []

    def spy_exchange(code, verifier):
        calls.append(code)
        return {"access_token": "x", "refresh_token": "y"}

    monkeypatch.setattr(ga, "_exchange_code_for_tokens", spy_exchange)

    result = mgr.submit_code(_TENANT, "   \n  ")
    assert result.status == "failed"
    assert "required" in (result.error or "").lower()
    assert calls == []


# ── submit_code: idempotency ─────────────────────────────────────────────


def test_submit_code_is_idempotent_after_success(monkeypatch):
    """Once connected, a duplicate submit-code (e.g. frontend retry,
    user double-click) must be a no-op. Specifically: don't re-call
    Google's token endpoint with a code that's already been
    redeemed."""
    mgr = _fresh_manager()
    mgr.start_login(_TENANT)

    captured_writes: list = []
    _stub_db(monkeypatch, captured_writes)

    exchange_calls = []

    def counting_exchange(code, verifier):
        exchange_calls.append(code)
        return {
            "access_token": "ya29.access",
            "refresh_token": "1//refresh",
            "expires_in": 3599,
        }

    monkeypatch.setattr(ga, "_exchange_code_for_tokens", counting_exchange)

    first = mgr.submit_code(_TENANT, "AUTH_CODE")
    assert first.status == "connected"
    assert len(exchange_calls) == 1
    rows_after_first = len(captured_writes)

    # Second submit: must not re-exchange, must not re-write the vault.
    second = mgr.submit_code(_TENANT, "AUTH_CODE")
    assert second.status == "connected"
    assert second.connected is True
    assert len(exchange_calls) == 1  # NOT incremented
    assert len(captured_writes) == rows_after_first


def test_submit_code_returns_none_for_unknown_tenant():
    """No /start ever happened for this tenant → /submit-code is
    nonsensical. Manager returns None; the route layer translates to
    404."""
    mgr = _fresh_manager()
    assert mgr.submit_code("no-such-tenant", "any-code") is None


# ── _exchange_code_for_tokens: HTTP layer ────────────────────────────────


def test_exchange_code_for_tokens_posts_pkce_payload(monkeypatch):
    """Direct test of the HTTP layer: we POST form-urlencoded with
    every PKCE field Google's docs require. Missing any of these is
    an instant 400 in production."""
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "access_token": "ya29.x",
                "refresh_token": "1//y",
                "expires_in": 3599,
                "scope": "s",
                "token_type": "Bearer",
            }

    class FakeClient:
        def __init__(self, *a, **kw):
            captured["timeout"] = kw.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(ga.httpx, "Client", FakeClient)

    result = ga._exchange_code_for_tokens("THE_CODE", "THE_VERIFIER")
    assert result["access_token"] == "ya29.x"
    assert captured["url"] == ga.GOOGLE_TOKEN_URL
    payload = captured["data"]
    assert payload["grant_type"] == "authorization_code"
    assert payload["code"] == "THE_CODE"
    assert payload["code_verifier"] == "THE_VERIFIER"
    expected_id, expected_secret = ga._load_gemini_oauth_client()
    assert payload["client_id"] == expected_id
    assert payload["redirect_uri"] == ga.GEMINI_OAUTH_REDIRECT_URI
    # We send the bundled client_secret; the installed-app model
    # requires it even though it's not really secret.
    assert payload["client_secret"] == expected_secret


def test_exchange_code_for_tokens_raises_with_split_messages_on_4xx(monkeypatch):
    """A Google 4xx must raise `_OAuthExchangeError` with two distinct
    messages: `safe_message` for server logs (verbose) and
    `user_message` for the API response (sanitised). The split
    prevents leaking raw Google body / user-pasted code into browser-
    visible state."""

    class FakeResponse:
        status_code = 400

        def json(self):
            return {
                "error": "invalid_grant",
                "error_description": "Bad Request",
            }

        text = '{"error":"invalid_grant","error_description":"Bad Request"}'

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            return FakeResponse()

    monkeypatch.setattr(ga.httpx, "Client", FakeClient)

    with pytest.raises(ga._OAuthExchangeError) as exc:
        ga._exchange_code_for_tokens("any", "any")
    err = exc.value
    # Server-side message includes the raw error code for debug.
    assert "invalid_grant" in err.safe_message
    # User-facing message is the actionable, sanitised version.
    assert "authorization code" in err.user_message.lower()
    assert "invalid_grant" not in err.user_message  # raw code not leaked
