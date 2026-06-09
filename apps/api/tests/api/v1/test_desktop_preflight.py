"""Pure-logic tests for the desktop-control envelope-signing preflight.

``run_desktop_preflight`` backs the ``alpha desktop preflight run`` verb and the
fail-fast readiness hook. It reads the module-level ``settings`` singleton, so we
patch that (not a fresh ``Settings`` instance). No DB.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import settings
from app.services import desktop_control_service as svc


def _ed25519_key_b64url() -> str:
    raw = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_preflight_ok_for_hmac_default(monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "HMAC-SHA256", raising=False)
    result = svc.run_desktop_preflight()
    assert result["ok"] is True
    assert result["error"] is None
    assert result["algorithm"] == "HMAC-SHA256"


def test_preflight_fails_for_ed25519_without_key(monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", "", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID", "k1", raising=False)
    result = svc.run_desktop_preflight()
    assert result["ok"] is False
    assert result["algorithm"] == "Ed25519"
    assert result["error"]
    assert result["checks"][0]["ok"] is False


def test_preflight_ok_for_ed25519_with_valid_key(monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", _ed25519_key_b64url(), raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID", "k1", raising=False)
    result = svc.run_desktop_preflight()
    assert result["ok"] is True, result["error"]
    assert result["algorithm"] == "Ed25519"
