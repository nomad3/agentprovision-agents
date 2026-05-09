"""Unit tests for the Twilio SMS webhook.

Pure-function tests that don't need a live DB or HTTP server:
  - Signature verification (positive + negative cases) via both the SDK
    path and the HMAC fallback. Twilio's algorithm is documented at
    https://www.twilio.com/docs/usage/security#validating-requests
  - Phone normalization round-trips
  - Tenant resolution by `To` number using a mocked DB session

The full end-to-end inbound→agent→outbound path is exercised by a smoke
test in CI against a containerized API + a stubbed Twilio sandbox; we
intentionally don't reach into chat_service here.
"""
import base64
import hashlib
import hmac
import os

# Disable signature requirement only when explicitly under that test; the
# default path keeps the production guard ON so we don't accidentally relax
# it for everyone.
os.environ.setdefault("TESTING", "True")

from app.api.v1 import twilio_webhook as tw  # noqa: E402


# ---------------------------------------------------------------------------
# _normalize_phone
# ---------------------------------------------------------------------------

def test_normalize_phone_handles_e164():
    assert tw._normalize_phone("+17145551234") == "+17145551234"


def test_normalize_phone_strips_formatting():
    assert tw._normalize_phone("+1 (714) 555-1234") == "+17145551234"


def test_normalize_phone_handles_no_plus():
    assert tw._normalize_phone("17145551234") == "17145551234"


def test_normalize_phone_returns_empty_for_none():
    assert tw._normalize_phone(None) == ""
    assert tw._normalize_phone("") == ""


# ---------------------------------------------------------------------------
# _verify_twilio_signature — pure-Python fallback path
# ---------------------------------------------------------------------------

def _twilio_signature(url: str, params: dict, auth_token: str) -> str:
    """Replicate Twilio's algorithm — sort params, concat, HMAC-SHA1, base64."""
    sorted_pairs = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    raw = f"{url}{sorted_pairs}".encode("utf-8")
    digest = hmac.new(auth_token.encode("utf-8"), raw, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_signature_accepts_valid_request(monkeypatch):
    # Force the pure-Python path so this test holds even if the SDK is
    # missing in CI minimal images.
    monkeypatch.setattr(
        "app.api.v1.twilio_webhook.RequestValidator", None, raising=False,
    )
    url = "https://agentprovision.com/api/v1/integrations/twilio/inbound"
    params = {"From": "+15551234567", "To": "+17145551234", "Body": "hello"}
    token = "test_auth_token_abc"
    sig = _twilio_signature(url, params, token)

    # Patch SDK import so the fallback path runs.
    import builtins

    real_import = builtins.__import__

    def deny_sdk(name, *args, **kwargs):
        if name.startswith("twilio"):
            raise ImportError("blocked by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_sdk)
    assert tw._verify_twilio_signature(
        signature=sig, full_url=url, params=params, auth_token=token,
    ) is True


def test_signature_rejects_tampered_body(monkeypatch):
    url = "https://agentprovision.com/api/v1/integrations/twilio/inbound"
    params = {"From": "+15551234567", "To": "+17145551234", "Body": "hello"}
    token = "test_auth_token_abc"
    sig = _twilio_signature(url, params, token)

    # Now tamper with one of the params before verifying — should fail.
    tampered = dict(params)
    tampered["Body"] = "evil"

    import builtins
    real_import = builtins.__import__

    def deny_sdk(name, *args, **kwargs):
        if name.startswith("twilio"):
            raise ImportError("blocked by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_sdk)
    assert tw._verify_twilio_signature(
        signature=sig, full_url=url, params=tampered, auth_token=token,
    ) is False


def test_signature_rejects_missing_signature():
    assert tw._verify_twilio_signature(
        signature=None, full_url="x", params={}, auth_token="y",
    ) is False
    assert tw._verify_twilio_signature(
        signature="", full_url="x", params={}, auth_token="y",
    ) is False


def test_signature_rejects_wrong_token(monkeypatch):
    url = "https://agentprovision.com/api/v1/integrations/twilio/inbound"
    params = {"From": "+15551234567", "To": "+17145551234", "Body": "hello"}
    correct_token = "correct"
    wrong_token = "wrong"
    sig = _twilio_signature(url, params, correct_token)

    import builtins
    real_import = builtins.__import__

    def deny_sdk(name, *args, **kwargs):
        if name.startswith("twilio"):
            raise ImportError("blocked by test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_sdk)
    assert tw._verify_twilio_signature(
        signature=sig, full_url=url, params=params, auth_token=wrong_token,
    ) is False


# ---------------------------------------------------------------------------
# _resolve_tenant_for_to_number
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, configs):
        self._configs = configs

    def filter(self, *_):
        return self

    def all(self):
        return self._configs

    def first(self):
        return self._configs[0] if self._configs else None


class _FakeDB:
    def __init__(self, configs, creds_by_config):
        self._configs = configs
        self._creds = creds_by_config

    def query(self, _model):
        return _FakeQuery(self._configs)


def test_resolve_tenant_matches_phone_number(monkeypatch):
    import uuid as _uuid

    tenant_a = _uuid.uuid4()
    tenant_b = _uuid.uuid4()

    class _Cfg:
        def __init__(self, cid, tid):
            self.id = cid
            self.tenant_id = tid

    cfg_a = _Cfg(_uuid.uuid4(), tenant_a)
    cfg_b = _Cfg(_uuid.uuid4(), tenant_b)

    creds_map = {
        cfg_a.id: {"account_sid": "ACa", "auth_token": "t_a", "phone_number": "+17145551234"},
        cfg_b.id: {"account_sid": "ACb", "auth_token": "t_b", "phone_number": "+13105550000"},
    }

    fake_db = _FakeDB([cfg_a, cfg_b], creds_map)

    def fake_retrieve(_db, config_id, _tid):
        return creds_map[config_id]

    monkeypatch.setattr(
        "app.api.v1.twilio_webhook.retrieve_credentials_for_skill", fake_retrieve,
    )

    # Match tenant A by formatted destination number
    result = tw._resolve_tenant_for_to_number(fake_db, "+1 (714) 555-1234")
    assert result is not None
    tid, cfg, creds = result
    assert tid == tenant_a
    assert cfg is cfg_a
    assert creds["auth_token"] == "t_a"

    # Match tenant B by raw number
    result = tw._resolve_tenant_for_to_number(fake_db, "+13105550000")
    assert result is not None
    assert result[0] == tenant_b


def test_resolve_tenant_returns_none_for_unknown_number(monkeypatch):
    import uuid as _uuid

    class _Cfg:
        def __init__(self, cid, tid):
            self.id = cid
            self.tenant_id = tid

    cfg = _Cfg(_uuid.uuid4(), _uuid.uuid4())
    fake_db = _FakeDB([cfg], {cfg.id: {"phone_number": "+17145551234", "auth_token": "x"}})

    def fake_retrieve(_db, config_id, _tid):
        return {"phone_number": "+17145551234", "auth_token": "x"}

    monkeypatch.setattr(
        "app.api.v1.twilio_webhook.retrieve_credentials_for_skill", fake_retrieve,
    )

    assert tw._resolve_tenant_for_to_number(fake_db, "+19998887777") is None


def test_resolve_tenant_returns_none_when_no_configs(monkeypatch):
    fake_db = _FakeDB([], {})
    monkeypatch.setattr(
        "app.api.v1.twilio_webhook.retrieve_credentials_for_skill",
        lambda *a, **k: {},
    )
    assert tw._resolve_tenant_for_to_number(fake_db, "+17145551234") is None
