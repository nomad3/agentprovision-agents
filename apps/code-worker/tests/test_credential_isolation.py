"""Per-turn GitHub credential isolation — F01 cross-tenant token bleed.

The code-worker runs chat activities in a ``ThreadPoolExecutor`` (worker.py),
so two tenants' chat turns can be in-flight on the same process at once. The
old dispatcher wrote a PROCESS-GLOBAL ``os.environ["GITHUB_TOKEN"]`` per turn
(workflows.py) and the non-claude executors did a bare ``os.environ.copy()``
that inherited it — so tenant B's turn could overwrite the global and tenant
A's codex/gemini/copilot git op would authenticate with B's credential.

The fix: ``cli_runtime.build_base_env(task_input)`` builds a per-turn env with
THIS tenant's token applied (set-or-strip) and the dispatcher never writes the
global. claude.py already did this via ``_apply_git_credential_env``; these
tests pin the same guarantee for every subprocess executor.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import cli_runtime
import workflows as wf


TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


def _make_input(**overrides):
    base = dict(
        platform="claude_code",
        message="hello",
        tenant_id=TENANT_B,
        instruction_md_content="",
        mcp_config="",
        image_b64="",
        image_mime="",
        session_id="",
        model="",
        allowed_tools="",
        chat_session_id="sess-1234567890",
    )
    base.update(overrides)
    return wf.ChatCliInput(**base)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


@pytest.fixture
def fake_workspaces_root(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setattr(cli_runtime, "WORKSPACES_ROOT", Path(root))
    return root


# ── cli_runtime.build_base_env — the shared per-turn env builder ─────────

class TestBuildBaseEnv:
    def test_applies_this_tenants_token_over_a_stale_global(self, monkeypatch):
        # A prior tenant's turn left a process-global token behind; THIS tenant
        # has its own. The per-turn env must carry only this tenant's token.
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_FRESH_tenant_B")

        env = cli_runtime.build_base_env(_make_input(tenant_id=TENANT_B))

        assert env["GITHUB_TOKEN"] == "gho_FRESH_tenant_B"
        assert env["GH_TOKEN"] == "gho_FRESH_tenant_B"

    def test_strips_stale_global_when_tenant_has_no_token(self, monkeypatch):
        # No token for this tenant → any inherited global must be removed so the
        # system gh credential helper can't authenticate the wrong tenant.
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: None)

        env = cli_runtime.build_base_env(_make_input(tenant_id=TENANT_B))

        assert "GITHUB_TOKEN" not in env
        assert "GH_TOKEN" not in env

    def test_never_mutates_the_process_global(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_FRESH_tenant_B")

        cli_runtime.build_base_env(_make_input(tenant_id=TENANT_B))

        # The whole point: os.environ is left exactly as it was.
        assert os.environ["GITHUB_TOKEN"] == "gho_STALE_tenant_A"


# ── dispatcher must NOT write a process-global token ────────────────────

class TestDispatcherNoGlobalWrite:
    def test_execute_chat_cli_does_not_export_github_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_should_not_leak")
        # The dispatcher mkdir's a per-tenant session dir under /home/codeworker;
        # no-op it so the test runs anywhere (the assertion is about os.environ).
        monkeypatch.setattr(wf.os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(
            wf, "_execute_claude_chat",
            lambda *a, **kw: wf.ChatCliResult(response_text="x", success=True),
        )

        wf.execute_chat_cli(_make_input(platform="claude_code"))

        # The dispatcher no longer writes the process-global token (the bleed).
        assert "GITHUB_TOKEN" not in os.environ


# ── per-executor bleed: subprocess env carries this tenant's token ──────

class TestExecutorTokenIsolation:
    """Each subprocess executor's env must carry THIS tenant's token, never a
    stale process-global from a prior tenant's turn."""

    def test_codex(self, monkeypatch, tmp_path, fake_workspaces_root):
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_codex_tenant_B")
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk-fake"}},
        )
        session_dir = tmp_path / "s"
        session_dir.mkdir()
        (session_dir / "codex-last-message.txt").write_text("answer")
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["env"] = kwargs["env"]
            return _completed(returncode=0)

        monkeypatch.setattr(cli_runtime, "run_cli_with_heartbeat", fake_run)
        wf._execute_codex_chat(
            _make_input(platform="codex", tenant_id=TENANT_B),
            session_dir=str(session_dir), image_path="",
        )
        assert captured["env"].get("GITHUB_TOKEN") == "gho_codex_tenant_B"
        assert captured["env"].get("GH_TOKEN") == "gho_codex_tenant_B"

    def test_gemini(self, monkeypatch, tmp_path, fake_workspaces_root):
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-FAKE")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_gemini_tenant_B")
        session_dir = tmp_path / "s"
        session_dir.mkdir()
        monkeypatch.setattr(
            wf, "_prepare_gemini_home_apikey", lambda sd, mcp: str(session_dir),
        )
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["env"] = kwargs["env"]
            return _completed(returncode=0, stdout='{"result": "ok"}')

        monkeypatch.setattr(cli_runtime, "run_cli_with_heartbeat", fake_run)
        wf._execute_gemini_chat(
            _make_input(platform="gemini_cli", tenant_id=TENANT_B),
            session_dir=str(session_dir), image_path="",
        )
        assert captured["env"].get("GITHUB_TOKEN") == "gho_gemini_tenant_B"

    def test_copilot(self, monkeypatch, tmp_path, fake_workspaces_root):
        monkeypatch.setenv("GITHUB_TOKEN", "gho_STALE_tenant_A")
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "gho_copilot_tenant_B")
        session_dir = tmp_path / "s"
        session_dir.mkdir()
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: str(session_dir))
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["env"] = kwargs["env"]
            return _completed(
                returncode=0,
                stdout='{"type": "assistant.message", "data": {"content": "ok", "outputTokens": 1}}',
            )

        monkeypatch.setattr(cli_runtime, "run_cli_with_heartbeat", fake_run)
        wf._execute_copilot_chat(
            _make_input(platform="copilot_cli", tenant_id=TENANT_B),
            session_dir=str(session_dir),
        )
        # Copilot's highest-precedence auth var must be THIS tenant's token,
        # not the stale global it used to read from os.environ.
        assert captured["env"].get("COPILOT_GITHUB_TOKEN") == "gho_copilot_tenant_B"


# ── regression guard: every bleed-prone executor routes through build_base_env ──

class TestAllSubprocessExecutorsUseBuildBaseEnv:
    """codex/gemini/copilot/aider/goose/qwen all share the bare
    ``os.environ.copy()`` shape and relied on the dispatcher's process-global
    write for their token. Removing that write would silently strip their token
    unless they source their per-turn env from build_base_env. The three
    audit-confirmed executors are pinned behaviorally above; this static guard
    prevents any of the six from regressing to a bare ``os.environ.copy()``."""

    _EXECUTOR_DIR = Path(__file__).resolve().parent.parent / "cli_executors"

    @pytest.mark.parametrize(
        "module", ["codex", "gemini", "copilot", "aider", "goose", "qwen"]
    )
    def test_executor_sources_env_from_build_base_env(self, module):
        src = (self._EXECUTOR_DIR / f"{module}.py").read_text()
        assert "cli_runtime.build_base_env(" in src, (
            f"{module}.py must build its per-turn env via cli_runtime.build_base_env "
            f"(found a bare os.environ.copy() instead → F01 cross-tenant token bleed)"
        )
