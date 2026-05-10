"""Shared fixtures for the code-worker test suite.

The code-worker package is a flat module layout (worker.py, workflows.py,
session_manager.py at the package root) so we add the package directory to
``sys.path`` here, mirroring how the runtime entrypoint imports it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── Path setup ───────────────────────────────────────────────────────────
# apps/code-worker/tests/conftest.py -> apps/code-worker
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

# Phase 1.5 — make the canonical cli_orchestrator package importable for
# pytest. apps/code-worker/tests/conftest.py -> apps/code-worker -> apps
# -> <repo-root>; the canonical package lives at <repo-root>/packages/.
# At runtime the worker container COPYs that package into /app/, so the
# top-level ``cli_orchestrator`` import resolves natively in production.
REPO_ROOT = PACKAGE_ROOT.parent.parent
PACKAGES_DIR = REPO_ROOT / "packages"
if PACKAGES_DIR.is_dir() and str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))


# ── Required env (must be set before importing modules that read os.environ) ──
# The package reads API_BASE_URL / API_INTERNAL_KEY / TEMPORAL_ADDRESS at
# import time. Provide test-safe values so import never fails and external
# network calls have predictable URLs to mock.
os.environ.setdefault("API_BASE_URL", "http://api")
os.environ.setdefault("API_INTERNAL_KEY", "test-internal-key-not-real-32bytes-12")
os.environ.setdefault("TEMPORAL_ADDRESS", "temporal:7233")
os.environ.setdefault("CLAUDE_CODE_MODEL", "sonnet")


@pytest.fixture
def fake_mcp_config_json() -> str:
    """A realistic MCP config blob used by allowed-tools derivation tests."""
    return (
        '{"mcpServers": {'
        '  "agentprovision": {"url": "http://mcp:8086", "headers": {"X-Tenant-Id": "abc"}},'
        '  "github":         {"url": "http://mcp:8086"}'
        '}}'
    )


@pytest.fixture
def claude_token_response() -> dict:
    return {"session_token": "sk-ant-oat01-FAKE-TEST-TOKEN", "oauth_token": ""}


@pytest.fixture
def github_token_response() -> dict:
    return {"oauth_token": "ghp_FAKE_TOKEN", "session_token": ""}


@pytest.fixture
def codex_auth_payload() -> dict:
    return {
        "OPENAI_API_KEY": "fake",
        "tokens": {"id_token": "x", "access_token": "y", "refresh_token": "z"},
    }


@pytest.fixture
def chat_input_kwargs() -> dict:
    """Default kwargs for ChatCliInput used across tests."""
    return {
        "platform": "claude_code",
        "message": "hello world",
        "tenant_id": "tenant-aaa",
        "instruction_md_content": "",
        "mcp_config": "",
        "image_b64": "",
        "image_mime": "",
        "session_id": "",
        "model": "",
        "allowed_tools": "",
    }
