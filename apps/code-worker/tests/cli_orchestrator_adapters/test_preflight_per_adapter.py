"""Per-adapter preflight composition tests — Phase 3 commit 2.

Fixture-driven sanity per platform:

  - binary missing → PROVIDER_UNAVAILABLE
  - creds missing → NEEDS_AUTH
  - trust file absent → WORKSPACE_UNTRUSTED (codex only)
  - cloud api disabled → API_DISABLED (gemini_cli + copilot_cli)

The tests inject mocks via ``PreflightDeps.set_for_test`` so no Redis,
no httpx, no actual binary lookup is required.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli_orchestrator.adapters.base import ExecutionRequest
from cli_orchestrator.preflight import clear_caches as preflight_clear_caches
from cli_orchestrator.status import Status

from cli_orchestrator_adapters.claude_code import ClaudeCodeAdapter
from cli_orchestrator_adapters.codex import CodexAdapter
from cli_orchestrator_adapters.copilot_cli import CopilotCliAdapter
from cli_orchestrator_adapters.gemini_cli import GeminiCliAdapter
from cli_orchestrator_adapters.opencode import OpencodeAdapter
from cli_orchestrator_adapters.preflight_deps import PreflightDeps
from cli_orchestrator_adapters.shell import ShellAdapter


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    preflight_clear_caches()
    PreflightDeps.reset_for_test()
    yield
    preflight_clear_caches()
    PreflightDeps.reset_for_test()


def _req(*, payload=None, tenant_id="t-123"):
    return ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload=payload or {"message": "hi"}, tenant_id=tenant_id,
    )


# ── claude_code ──────────────────────────────────────────────────────────

def test_claude_code_binary_missing_returns_provider_unavailable(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
    )
    result = ClaudeCodeAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_claude_code_creds_missing_returns_needs_auth(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/claude",
    )
    PreflightDeps.get().set_for_test(credential_fetch=lambda p, t: None)
    result = ClaudeCodeAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_claude_code_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/claude",
    )
    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
    )
    result = ClaudeCodeAdapter().preflight(_req())
    assert result.ok is True


# ── codex ────────────────────────────────────────────────────────────────

def test_codex_binary_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    result = CodexAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_codex_creds_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/codex",
    )
    PreflightDeps.get().set_for_test(credential_fetch=lambda p, t: None)
    result = CodexAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_codex_workspace_trust_file_absent(monkeypatch):
    """Codex preflight returns WORKSPACE_UNTRUSTED when trust file is gone.

    We force ``Path.exists`` to False on every probe rather than
    monkey-patching the module-level ``_WORKSPACE_TRUST_FILES`` dict,
    because module-popping in earlier tests can leave us with two
    copies of ``_common`` and patching the wrong one is silent.
    """
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/codex",
    )
    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
    )
    monkeypatch.setattr(
        "cli_orchestrator.preflight.Path.exists", lambda self: False,
    )
    result = CodexAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.WORKSPACE_UNTRUSTED


def test_codex_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/codex",
    )
    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
    )
    monkeypatch.setattr(
        "cli_orchestrator.preflight.Path.exists", lambda self: True,
    )
    result = CodexAdapter().preflight(_req())
    assert result.ok is True


# ── gemini_cli ───────────────────────────────────────────────────────────

def test_gemini_binary_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    result = GeminiCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_gemini_creds_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/gemini",
    )
    PreflightDeps.get().set_for_test(credential_fetch=lambda p, t: None)
    result = GeminiCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_gemini_api_disabled(monkeypatch):
    """Stamp the Redis cache with '0' so check_cloud_api_enabled
    short-circuits to API_DISABLED without hitting the probe — robust
    against module-rebind issues from earlier import-drag tests."""
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/gemini",
    )
    cache = {"cli_orchestrator:preflight:cloud_api:t-123:gemini_cli": b"0"}

    class _StubRedis:
        def get(self, k):
            return cache.get(k)

        def setex(self, k, ttl, v):
            cache[k] = v.encode() if isinstance(v, str) else v

        def ping(self):
            return True

    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
        redis_client=_StubRedis(),
    )
    result = GeminiCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.API_DISABLED


def test_gemini_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/gemini",
    )
    cache = {"cli_orchestrator:preflight:cloud_api:t-123:gemini_cli": b"1"}

    class _StubRedis:
        def get(self, k):
            return cache.get(k)

        def setex(self, k, ttl, v):
            cache[k] = v.encode() if isinstance(v, str) else v

        def ping(self):
            return True

    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
        redis_client=_StubRedis(),
    )
    result = GeminiCliAdapter().preflight(_req())
    assert result.ok is True


# ── copilot_cli ──────────────────────────────────────────────────────────

def test_copilot_binary_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    result = CopilotCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_copilot_creds_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/copilot",
    )
    PreflightDeps.get().set_for_test(credential_fetch=lambda p, t: None)
    result = CopilotCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.NEEDS_AUTH


def test_copilot_api_disabled(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/copilot",
    )
    cache = {"cli_orchestrator:preflight:cloud_api:t-123:copilot_cli": b"0"}

    class _StubRedis:
        def get(self, k):
            return cache.get(k)

        def setex(self, k, ttl, v):
            cache[k] = v.encode() if isinstance(v, str) else v

        def ping(self):
            return True

    PreflightDeps.get().set_for_test(
        credential_fetch=lambda p, t: {"oauth_token": "x"},
        redis_client=_StubRedis(),
    )
    result = CopilotCliAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.API_DISABLED


# ── opencode + shell — only binary check ────────────────────────────────

def test_opencode_binary_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    result = OpencodeAdapter().preflight(_req())
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_opencode_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which",
        lambda name: "/bin/opencode",
    )
    result = OpencodeAdapter().preflight(_req())
    assert result.ok is True


def test_shell_no_cmd_returns_provider_unavailable():
    req = ExecutionRequest(
        chain=("shell",), platform="shell", payload={}, tenant_id="t",
    )
    result = ShellAdapter().preflight(req)
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_shell_binary_missing(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: None,
    )
    req = ExecutionRequest(
        chain=("shell",), platform="shell",
        payload={"cmd": ["nonsuch", "--help"]}, tenant_id="t",
    )
    result = ShellAdapter().preflight(req)
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_shell_happy(monkeypatch):
    monkeypatch.setattr(
        "cli_orchestrator.preflight.shutil.which", lambda name: "/bin/echo",
    )
    req = ExecutionRequest(
        chain=("shell",), platform="shell",
        payload={"cmd": ["echo", "hi"]}, tenant_id="t",
    )
    result = ShellAdapter().preflight(req)
    assert result.ok is True


# ── temporal_activity heartbeat-staleness ──────────────────────────────

def test_temporal_activity_stale_heartbeat_returns_provider_unavailable(monkeypatch):
    from cli_orchestrator.adapters import temporal_activity as ta_mod
    monkeypatch.setattr(
        ta_mod, "_QUEUE_PROBE_OVERRIDE",
        (lambda k: None, lambda k, ttl, v: None, lambda: 0.0),  # ts=0 → very stale
    )
    adapter = ta_mod.TemporalActivityAdapter("claude_code")
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    result = adapter.preflight(req)
    assert result.ok is False
    assert result.status is Status.PROVIDER_UNAVAILABLE


def test_temporal_activity_fresh_heartbeat_returns_ok(monkeypatch):
    import time as _time
    from cli_orchestrator.adapters import temporal_activity as ta_mod
    monkeypatch.setattr(
        ta_mod, "_QUEUE_PROBE_OVERRIDE",
        (lambda k: None, lambda k, ttl, v: None, lambda: _time.time() - 5.0),
    )
    adapter = ta_mod.TemporalActivityAdapter("claude_code")
    req = ExecutionRequest(
        chain=("claude_code",), platform="claude_code",
        payload={}, tenant_id="t",
    )
    result = adapter.preflight(req)
    assert result.ok is True
