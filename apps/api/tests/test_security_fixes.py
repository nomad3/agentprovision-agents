import pytest
import os
import sys
import importlib
from unittest.mock import patch
from pydantic import ValidationError


def test_secret_key_has_no_insecure_default():
    """Settings must raise on startup when critical env vars are missing."""
    env_without_secrets = {k: v for k, v in os.environ.items()
                           if k not in ("SECRET_KEY", "MCP_API_KEY", "API_INTERNAL_KEY")}
    with patch.dict(os.environ, env_without_secrets, clear=True):
        # Remove any cached module so the reload triggers a fresh Settings() call
        sys.modules.pop("app.core.config", None)
        with pytest.raises((ValidationError, Exception)) as exc_info:
            importlib.import_module("app.core.config")
        # Verify the error is about missing required fields, not some unrelated failure
        error_str = str(exc_info.value)
        assert any(field in error_str for field in [
            "SECRET_KEY", "MCP_API_KEY", "API_INTERNAL_KEY",
            "secret_key", "mcp_api_key", "api_internal_key",
        ]), f"Error should mention missing required fields, got: {error_str}"


os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests")
os.environ.setdefault("MCP_API_KEY", "test-mcp-key")
os.environ.setdefault("API_INTERNAL_KEY", "test-internal-key")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/agentprovision")

from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_oauth_test_client():
    """Create a minimal FastAPI test app with just the OAuth router mounted,
    bypassing database initialisation which requires a live PostgreSQL server."""
    # Patch init_db before importing app.main so the module-level DB call is a no-op
    with patch("app.db.init_db.init_db", return_value=None), \
         patch("app.db.session.SessionLocal", return_value=MagicMock()):
        # Reload the oauth module in isolation to avoid DB dependency
        import importlib
        import app.api.v1.oauth as oauth_module
        importlib.reload(oauth_module)

    test_app = FastAPI()

    # Provide a stub DB dependency so the router can be mounted without a live DB
    from app.api import deps

    def _stub_db():
        yield MagicMock()

    test_app.dependency_overrides[deps.get_db] = _stub_db
    test_app.include_router(oauth_module.router, prefix="/api/v1/oauth")
    return TestClient(test_app)


def test_oauth_callback_error_escapes_xss():
    """XSS payload in ?error must be HTML-escaped in the response."""
    client = _make_oauth_test_client()
    xss = "<script>alert(1)</script>"
    resp = client.get(f"/api/v1/oauth/google/callback?error={xss}")
    assert resp.status_code == 200
    body = resp.text
    assert "<script>alert(1)</script>" not in body, "Raw XSS tag must NOT appear in response"
    assert "&lt;script&gt;" in body, "Escaped form must appear in response"


def test_oauth_callback_img_injection_escaped():
    """HTML injection via error param must be escaped in <p> tag."""
    client = _make_oauth_test_client()
    resp = client.get('/api/v1/oauth/google/callback?error="><img src=x onerror=alert(1)>')
    body = resp.text
    assert '<img' not in body, "Raw <img> must not appear"
    assert '&lt;img' in body, "Escaped <img> must appear"
