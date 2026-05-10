"""Tests for the per-platform chat helpers in workflows.py.

Targets:
  * ``_execute_codex_chat``    — line 1246-1328
  * ``_execute_gemini_chat``   — line 1559-1722
  * ``_execute_copilot_chat``  — line 1825-2016
  * ``_execute_opencode_chat`` — line 2081-2151
  * ``_execute_opencode_chat_cli`` — line 2154-2181
  * ``_execute_codex_code_task`` — line 1331-1379

All four helpers follow the same pattern: fetch credentials → prepare a
session/home directory → spawn the CLI subprocess via
``_run_cli_with_heartbeat`` → parse output. We mock the credential fetch and
the subprocess wrapper so each test asserts on the parsing/dispatch logic
rather than re-running real CLIs.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import cli_runtime
import workflows as wf


def _make_input(**overrides):
    base = dict(
        platform="codex",
        message="hello",
        tenant_id="tenant-aaa",
        instruction_md_content="",
        mcp_config="",
        image_b64="",
        image_mime="",
        session_id="",
        model="",
        allowed_tools="",
    )
    base.update(overrides)
    return wf.ChatCliInput(**base)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


# ── _execute_codex_chat ──────────────────────────────────────────────────

class TestExecuteCodexChat:
    def test_credentials_fetch_failure_returns_error(self, monkeypatch, tmp_path):
        def boom(integration, tenant_id):
            raise RuntimeError("vault down")

        monkeypatch.setattr(wf, "_fetch_integration_credentials", boom)

        out = wf._execute_codex_chat(
            _make_input(), session_dir=str(tmp_path), image_path="",
        )
        assert out.success is False
        assert "Failed to load Codex credentials" in out.error

    def test_missing_auth_payload_returns_not_connected(self, monkeypatch, tmp_path):
        # Empty creds dict.
        monkeypatch.setattr(wf, "_fetch_integration_credentials", lambda i, t: {})

        out = wf._execute_codex_chat(
            _make_input(), session_dir=str(tmp_path), image_path="",
        )
        assert out.success is False
        assert "not connected" in out.error.lower()

    def test_invalid_json_in_session_token_returns_helpful_error(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"session_token": "not valid json {"},
        )

        out = wf._execute_codex_chat(
            _make_input(), session_dir=str(tmp_path), image_path="",
        )
        assert out.success is False
        assert "auth.json" in out.error

    def test_happy_path_returns_response_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk-fake"}},
        )

        # Pre-write the output file the helper reads after subprocess returns.
        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()
        output_file = session_dir / "codex-last-message.txt"
        output_file.write_text("Codex says hi")

        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout="", stderr=""),
        )

        out = wf._execute_codex_chat(
            _make_input(), session_dir=str(session_dir), image_path="",
        )
        assert out.success is True
        assert out.response_text == "Codex says hi"
        assert out.metadata["platform"] == "codex"
        # Synthetic session id is added when stdout doesn't contain one.
        assert out.metadata["codex_session_id"]

    def test_non_zero_exit_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk-fake"}},
        )

        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()

        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=1, stdout="", stderr="rate limit"),
        )

        out = wf._execute_codex_chat(
            _make_input(), session_dir=str(session_dir), image_path="",
        )
        assert out.success is False
        assert "exit 1" in out.error
        assert "rate limit" in out.error

    def test_image_path_added_to_command(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk-fake"}},
        )
        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()
        (session_dir / "codex-last-message.txt").write_text("ok")

        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return _completed(returncode=0)

        monkeypatch.setattr(cli_runtime, "run_cli_with_heartbeat", fake_run)

        wf._execute_codex_chat(
            _make_input(), session_dir=str(session_dir), image_path="/tmp/img.jpg",
        )
        assert "--image" in captured["cmd"]
        assert "/tmp/img.jpg" in captured["cmd"]


# ── _execute_gemini_chat ─────────────────────────────────────────────────

class TestExecuteGeminiChat:
    @pytest.fixture(autouse=True)
    def _no_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_no_credentials_returns_not_connected(self, monkeypatch, tmp_path):
        # Force OAuth path (no api_key) and have creds fetch return empty.
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials", lambda i, t: {},
        )
        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(tmp_path), image_path="",
        )
        assert out.success is False
        assert "not connected" in out.error.lower()

    def test_creds_fetch_exception_returns_error(self, monkeypatch, tmp_path):
        def boom(i, t):
            raise RuntimeError("net failed")

        monkeypatch.setattr(wf, "_fetch_integration_credentials", boom)
        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(tmp_path), image_path="",
        )
        assert out.success is False
        assert "Failed to load Gemini credentials" in out.error

    def test_api_key_path_runs_helper_and_parses_json(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-FAKE")

        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()

        # Stub _prepare_gemini_home_apikey to avoid the FS dance.
        monkeypatch.setattr(
            wf, "_prepare_gemini_home_apikey",
            lambda sd, mcp: str(session_dir),
        )
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(
                returncode=0,
                stdout='{"result": "Gemini speaking", "model": "gemini-2.5-pro"}',
                stderr="",
            ),
        )

        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(session_dir), image_path="",
        )
        assert out.success is True
        assert out.response_text == "Gemini speaking"
        assert out.metadata["platform"] == "gemini_cli"
        assert out.metadata["model"] == "gemini-2.5-pro"

    def test_non_zero_exit_includes_tool_error_metadata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza")
        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()
        monkeypatch.setattr(
            wf, "_prepare_gemini_home_apikey", lambda sd, mcp: str(session_dir),
        )

        # stderr contains a tool-error pattern; helper should extract it.
        stderr_text = "Error executing tool default_api:list_files: not authorized\n"
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=1, stdout="", stderr=stderr_text),
        )

        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(session_dir), image_path="",
        )
        assert out.success is False
        assert "exit 1" in out.error
        # Tool-error metadata captured even on failure.
        tools_called = out.metadata["tools_called"]
        assert any("default_api:list_files" in t["name"] for t in tools_called)

    def test_empty_stdout_returns_no_output_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza")
        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()
        monkeypatch.setattr(
            wf, "_prepare_gemini_home_apikey", lambda sd, mcp: str(session_dir),
        )
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout="", stderr=""),
        )

        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(session_dir), image_path="",
        )
        assert out.success is False
        assert "no output" in out.error.lower()

    def test_oauth_path_uses_prepare_gemini_home(self, monkeypatch, tmp_path):
        """When no api_key in env or creds, helper falls into OAuth branch
        and calls ``_prepare_gemini_home`` (line 1599)."""
        session_dir = tmp_path / "tenant-aaa"
        session_dir.mkdir()
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {
                "oauth_creds": json.dumps({"access_token": "x", "refresh_token": "y"}),
                "email": "u@x.com",
            },
        )

        captured = {}

        def fake_prep(sd, payload, mcp):
            captured["payload"] = payload
            return str(session_dir)

        monkeypatch.setattr(wf, "_prepare_gemini_home", fake_prep)
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout='{"result":"x"}'),
        )

        out = wf._execute_gemini_chat(
            _make_input(platform="gemini_cli"),
            session_dir=str(session_dir), image_path="",
        )
        assert out.success is True
        assert captured["payload"]["email"] == "u@x.com"


# ── _execute_copilot_chat ────────────────────────────────────────────────

class TestExecuteCopilotChat:
    def test_no_token_returns_not_connected(self, monkeypatch, tmp_path):
        # Clear env and have github fetch return None.
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: None)

        out = wf._execute_copilot_chat(_make_input(platform="copilot_cli"), str(tmp_path))
        assert out.success is False
        assert "not connected" in out.error.lower()

    def test_token_from_env_skips_fetch(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_envvar")

        called = {"n": 0}

        def fake_fetch(tid):
            called["n"] += 1
            return None

        monkeypatch.setattr(wf, "_fetch_github_token", fake_fetch)
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(
                returncode=0,
                stdout=json.dumps({
                    "type": "assistant.message",
                    "data": {"content": "Hi from Copilot", "outputTokens": 10},
                }),
            ),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert called["n"] == 0  # env value was used, no fetch
        assert out.success is True
        assert out.response_text == "Hi from Copilot"
        assert out.metadata["output_tokens"] == 10

    def test_jsonl_with_no_assistant_message_returns_failure(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp")
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(
                returncode=0,
                stdout='{"type":"session.skills_loaded"}\n{"type":"session.completed"}\n',
            ),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert out.success is False
        assert "no parseable assistant message" in out.error

    def test_non_zero_exit_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp")
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=2, stdout="", stderr="quota exceeded"),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert out.success is False
        assert "exit 2" in out.error
        assert "quota exceeded" in out.error

    def test_empty_stdout_returns_no_output(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp")
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout=""),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert out.success is False
        assert "no output" in out.error.lower()

    def test_result_event_yields_premium_request_metadata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp")
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)

        stream = "\n".join([
            json.dumps({
                "type": "assistant.message",
                "data": {"content": "Final answer.", "outputTokens": 5},
            }),
            json.dumps({
                "type": "result",
                "sessionId": "sess-123",
                "exitCode": 0,
                "usage": {
                    "premiumRequests": 1,
                    "totalApiDurationMs": 1000,
                    "sessionDurationMs": 1500,
                    "codeChanges": {"linesAdded": 5},
                },
            }),
        ])
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout=stream),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "Final answer."
        assert out.metadata["premium_requests"] == 1
        assert out.metadata["api_duration_ms"] == 1000
        assert out.metadata["session_duration_ms"] == 1500
        assert out.metadata["copilot_code_changes"]["linesAdded"] == 5

    def test_tool_call_message_falls_back_to_no_tool_message(
        self, monkeypatch, tmp_path,
    ):
        """The helper prefers an assistant.message with NO toolRequests
        as the final answer — line 1948-1952."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp")
        monkeypatch.setattr(wf, "_prepare_copilot_home", lambda sd, mcp: sd)

        stream = "\n".join([
            # Tool-call turn — should be ignored as the answer.
            json.dumps({
                "type": "assistant.message",
                "data": {
                    "content": "Calling a tool now",
                    "toolRequests": [{"id": "1", "name": "fs.read"}],
                    "outputTokens": 3,
                },
            }),
            # Final answer — preferred.
            json.dumps({
                "type": "assistant.message",
                "data": {"content": "Done.", "outputTokens": 2},
            }),
        ])
        monkeypatch.setattr(
            cli_runtime, "run_cli_with_heartbeat",
            lambda cmd, **kw: _completed(returncode=0, stdout=stream),
        )

        out = wf._execute_copilot_chat(
            _make_input(platform="copilot_cli"), str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "Done."
        assert out.metadata["output_tokens"] == 5  # 3 + 2 summed


# ── _execute_opencode_chat ───────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestExecuteOpencodeChat:
    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        # Reset module-level _opencode_sessions across tests.
        wf._opencode_sessions.clear()
        yield
        wf._opencode_sessions.clear()

    def test_creates_session_then_sends_message(self, monkeypatch, tmp_path):
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/session"):
                return _FakeResp(200, {"id": "sess-x"})
            # message endpoint
            return _FakeResp(200, {
                "parts": [{"type": "text", "text": "Local Gemma response"}],
                "usage": {"prompt_tokens": 10},
            })

        monkeypatch.setattr(wf.httpx, "post", fake_post)

        out = wf._execute_opencode_chat(
            _make_input(platform="opencode"), str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "Local Gemma response"
        assert out.metadata["platform"] == "opencode"
        assert wf._opencode_sessions["tenant-aaa"] == "sess-x"
        assert len(calls) == 2

    def test_reuses_existing_session(self, monkeypatch, tmp_path):
        wf._opencode_sessions["tenant-aaa"] = "existing-sess"

        calls = []

        def fake_post(url, **kwargs):
            calls.append(url)
            return _FakeResp(200, {"parts": [{"type": "text", "text": "x"}]})

        monkeypatch.setattr(wf.httpx, "post", fake_post)

        wf._execute_opencode_chat(
            _make_input(platform="opencode"), str(tmp_path),
        )
        # Only the message POST — no /session call.
        assert all("/session/existing-sess/message" in u for u in calls)
        assert len(calls) == 1

    def test_falls_back_to_cli_on_server_error(self, monkeypatch, tmp_path):
        def fake_post(url, **kwargs):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(wf.httpx, "post", fake_post)

        # The fallback CLI uses subprocess.run.
        def fake_subprocess_run(cmd, **kw):
            return _completed(
                returncode=0,
                stdout=json.dumps({"response": "CLI answer"}),
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_subprocess_run)

        out = wf._execute_opencode_chat(
            _make_input(platform="opencode"), str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "CLI answer"
        assert out.metadata["platform"] == "opencode_cli"

    def test_response_falls_back_to_legacy_field(self, monkeypatch, tmp_path):
        """If the new ``parts`` shape is missing, helper falls back to the
        legacy ``response`` field (line 2138-2139)."""

        def fake_post(url, **kwargs):
            if url.endswith("/session"):
                return _FakeResp(200, {"id": "sess"})
            # No 'parts', use legacy 'response'.
            return _FakeResp(200, {"response": "legacy text"})

        monkeypatch.setattr(wf.httpx, "post", fake_post)

        out = wf._execute_opencode_chat(
            _make_input(platform="opencode"), str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "legacy text"


class TestExecuteOpencodeChatCli:
    """The fallback CLI path used when the OpenCode server is unreachable."""

    def test_cli_failure_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf.subprocess, "run",
            lambda cmd, **kw: _completed(returncode=1, stdout="", stderr="boom"),
        )
        out = wf._execute_opencode_chat_cli(
            _make_input(platform="opencode"), str(tmp_path),
        )
        assert out.success is False
        assert "OpenCode CLI failed" in out.error

    def test_cli_subprocess_exception_returns_error(self, monkeypatch, tmp_path):
        def boom(*a, **kw):
            raise OSError("not found")

        monkeypatch.setattr(wf.subprocess, "run", boom)
        out = wf._execute_opencode_chat_cli(
            _make_input(platform="opencode"), str(tmp_path),
        )
        assert out.success is False
        assert "not found" in out.error


# ── _execute_codex_code_task ─────────────────────────────────────────────

class TestExecuteCodexCodeTask:
    """The Codex fallback path inside the code-task activity."""

    def test_credentials_failure_raises(self, monkeypatch, tmp_path):
        def boom(integration, tenant_id):
            raise RuntimeError("vault down")

        monkeypatch.setattr(wf, "_fetch_integration_credentials", boom)

        with pytest.raises(RuntimeError, match="Failed to load Codex"):
            wf._execute_codex_code_task(
                wf.CodeTaskInput(task_description="x", tenant_id="t"),
                prompt="do thing",
                session_dir=str(tmp_path),
            )

    def test_missing_auth_raises_not_connected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials", lambda i, t: {},
        )
        with pytest.raises(RuntimeError, match="not connected"):
            wf._execute_codex_code_task(
                wf.CodeTaskInput(task_description="x", tenant_id="t"),
                prompt="do thing",
                session_dir=str(tmp_path),
            )

    def test_invalid_json_auth_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"session_token": "{not json"},
        )
        with pytest.raises(RuntimeError, match="auth.json"):
            wf._execute_codex_code_task(
                wf.CodeTaskInput(task_description="x", tenant_id="t"),
                prompt="do thing",
                session_dir=str(tmp_path),
            )

    def test_happy_path_returns_response_and_metadata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk"}},
        )

        # The helper writes config files to session_dir/.codex — use real fs.
        session_dir = tmp_path / "session"
        session_dir.mkdir()

        # Drop a fake last-message file the helper reads.
        last_msg = session_dir / "codex-code-task-last-message.txt"
        last_msg.write_text("Codex says: done")

        def fake_long(cmd, **kw):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=json.dumps({"type": "session_configured", "model": "gpt-5"}),
                stderr="",
            )

        monkeypatch.setattr(wf, "_run_long_command", fake_long)

        text, meta = wf._execute_codex_code_task(
            wf.CodeTaskInput(task_description="x", tenant_id="t"),
            prompt="do thing",
            session_dir=str(session_dir),
        )
        assert text == "Codex says: done"
        assert meta["platform"] == "codex"
        assert meta["fallback_from"] == "claude_code"

    def test_empty_stdout_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            wf, "_fetch_integration_credentials",
            lambda i, t: {"auth_json": {"OPENAI_API_KEY": "sk"}},
        )
        session_dir = tmp_path / "session"
        session_dir.mkdir()

        monkeypatch.setattr(
            wf, "_run_long_command",
            lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr=""),
        )

        with pytest.raises(RuntimeError, match="no output"):
            wf._execute_codex_code_task(
                wf.CodeTaskInput(task_description="x", tenant_id="t"),
                prompt="x", session_dir=str(session_dir),
            )
