"""Pure-logic tests for the desktop-control envelope-signing preflight.

``run_desktop_preflight`` backs the ``alpha desktop preflight run`` operator
gate and the startup readiness log. It reads the module-level ``settings``
singleton, so we patch that (not a fresh ``Settings`` instance). No DB.
"""
import base64

import pytest
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


def test_preflight_reports_normalized_algorithm_for_operator_gate(monkeypatch):
    # A whitespace-padded algorithm must still report the canonical "Ed25519"
    # so the operator-facing gate and startup log report the real mode rather
    # than silently degrading to an unsupported value.
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", " Ed25519 ", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", "", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID", "k1", raising=False)
    result = svc.run_desktop_preflight()
    assert result["ok"] is False
    assert result["algorithm"] == "Ed25519"


@pytest.mark.asyncio
async def test_startup_preflight_does_not_crash_api_without_ed25519_key(monkeypatch, caplog):
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_SIGNING_ALGORITHM", "Ed25519", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_PRIVATE_KEY", "", raising=False)
    monkeypatch.setattr(settings, "DESKTOP_COMMAND_ENVELOPE_ED25519_KEY_ID", "k1", raising=False)

    from app.services.desktop_control_preflight import startup_desktop_control_preflight

    caplog.set_level("WARNING")
    await startup_desktop_control_preflight()
    assert "native control fail-closed" in caplog.text
