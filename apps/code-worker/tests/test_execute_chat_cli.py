"""Tests for execute_chat_cli — the platform dispatcher.

execute_chat_cli is a sync activity. Its responsibilities are:
  1. Fetch the tenant's GitHub token from the internal API and configure git.
  2. Build a per-tenant session directory.
  3. Optionally write user-supplied image bytes to disk.
  4. Dispatch to the right ``_execute_<platform>_chat`` helper.

We mock every external boundary (httpx, subprocess.run, the per-platform
helpers themselves) so the test stays a unit test and never hits the network.
"""
from __future__ import annotations

import os

import pytest

import workflows as wf


def _make_input(**overrides) -> wf.ChatCliInput:
    base = dict(
        platform="claude_code",
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


@pytest.fixture(autouse=True)
def _isolate_session_dir(monkeypatch, tmp_path):
    """Redirect /home/codeworker/st_sessions into pytest tmp_path."""
    sessions_root = tmp_path / "st_sessions"
    sessions_root.mkdir()

    original = os.path.join

    def patched(*parts):
        if parts and isinstance(parts[0], str) and parts[0].startswith(
            "/home/codeworker/st_sessions"
        ):
            return original(str(sessions_root), *parts[1:])
        return original(*parts)

    monkeypatch.setattr(wf.os.path, "join", patched)
    yield


@pytest.fixture(autouse=True)
def _stub_github_token(monkeypatch):
    """Default: no GitHub token, no remote configuration."""
    monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: None)
    # Also short-circuit any subprocess.run calls (git remote / gh auth).
    monkeypatch.setattr(wf.subprocess, "run", lambda *a, **kw: None)
    yield


class TestPlatformDispatch:
    """Each known platform dispatches to its own helper exactly once."""

    @pytest.mark.parametrize(
        "platform, helper_name",
        [
            ("claude_code", "_execute_claude_chat"),
            ("codex", "_execute_codex_chat"),
            ("copilot_cli", "_execute_copilot_chat"),
            ("gemini_cli", "_execute_gemini_chat"),
            ("opencode", "_execute_opencode_chat"),
        ],
    )
    def test_dispatches_to_helper(self, monkeypatch, platform, helper_name):
        sentinel = wf.ChatCliResult(response_text="OK", success=True)
        called: list[tuple] = []

        def fake_helper(*args, **kwargs):
            called.append((args, kwargs))
            return sentinel

        monkeypatch.setattr(wf, helper_name, fake_helper)

        out = wf.execute_chat_cli(_make_input(platform=platform))

        assert out is sentinel
        assert len(called) == 1, f"{helper_name} should be called exactly once"

    def test_unsupported_platform_returns_failure(self, monkeypatch):
        out = wf.execute_chat_cli(_make_input(platform="bogus_cli"))
        assert out.success is False
        assert "Unsupported" in out.error

    def test_helper_exception_is_caught_and_returned(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(wf, "_execute_claude_chat", boom)
        out = wf.execute_chat_cli(_make_input(platform="claude_code"))
        assert out.success is False
        assert "disk full" in out.error


class TestImageHandling:
    """When image_b64 + image_mime are provided, the file lands on disk."""

    def test_image_bytes_written_to_session_dir(self, monkeypatch, tmp_path):
        captured: dict = {}

        def fake_helper(task_input, session_dir, image_path):
            captured["session_dir"] = session_dir
            captured["image_path"] = image_path
            return wf.ChatCliResult(response_text="ok", success=True)

        monkeypatch.setattr(wf, "_execute_codex_chat", fake_helper)

        # 'AAAA' base64-decodes to 3 NUL bytes; enough to verify a write.
        wf.execute_chat_cli(_make_input(
            platform="codex", image_b64="QUJD", image_mime="image/jpeg",
        ))

        assert captured["image_path"].endswith("user_image.jpg")
        assert os.path.exists(captured["image_path"])
        # Bytes from "QUJD" base64 = b"ABC".
        assert open(captured["image_path"], "rb").read() == b"ABC"

    def test_no_image_means_empty_image_path(self, monkeypatch):
        captured: dict = {}

        def fake_helper(task_input, session_dir, image_path):
            captured["image_path"] = image_path
            return wf.ChatCliResult(response_text="ok", success=True)

        monkeypatch.setattr(wf, "_execute_gemini_chat", fake_helper)
        wf.execute_chat_cli(_make_input(platform="gemini_cli"))
        assert captured["image_path"] == ""


class TestGithubTokenIntegration:
    """When a GitHub token is found, it is exported and git is configured."""

    def test_token_wires_git_remote_and_gh_auth(self, monkeypatch):
        seen: list[list] = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            class R:
                returncode = 0
                stdout = b""
                stderr = b""
            return R()

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        monkeypatch.setattr(wf, "_fetch_github_token", lambda tid: "ghp_abc")
        monkeypatch.setattr(
            wf, "_execute_claude_chat",
            lambda *a, **kw: wf.ChatCliResult(response_text="x", success=True),
        )

        wf.execute_chat_cli(_make_input(platform="claude_code"))

        # Two subprocess.run calls expected: git remote set-url + gh auth login.
        joined = [" ".join(c) if isinstance(c, list) else c for c in seen]
        assert any("remote" in s and "set-url" in s for s in joined)
        assert any("gh" in s and "auth" in s and "login" in s for s in joined)
        # Token must be exported into the env.
        assert os.environ.get("GITHUB_TOKEN") == "ghp_abc"


# ── _execute_claude_chat smoke (covers JSON parse path) ─────────────────

class TestExecuteClaudeChat:
    def test_missing_token_returns_friendly_error(self, monkeypatch):
        # Patch the module-private second-definition that the helper actually
        # binds — both names point at the same function object.
        monkeypatch.setattr(wf, "_fetch_claude_token", lambda tid: None)
        result = wf._execute_claude_chat(
            _make_input(platform="claude_code"), session_dir="/tmp/x",
        )
        assert result.success is False
        assert "not connected" in result.error.lower()

    def test_parses_json_response(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wf, "_fetch_claude_token", lambda tid: "tok")

        import subprocess as sp

        fake_completed = sp.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout='{"result": "hi", "usage": {"input_tokens": 1, "output_tokens": 2}, "model": "claude-x", "session_id": "s", "total_cost_usd": 0.0}',
            stderr="",
        )
        monkeypatch.setattr(
            wf, "_run_cli_with_heartbeat",
            lambda cmd, **kw: fake_completed,
        )

        out = wf._execute_claude_chat(
            _make_input(platform="claude_code"), session_dir=str(tmp_path),
        )
        assert out.success is True
        assert out.response_text == "hi"
        assert out.metadata["platform"] == "claude_code"
        assert out.metadata["input_tokens"] == 1

    def test_non_zero_exit_returns_error_with_truncated_stderr(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wf, "_fetch_claude_token", lambda tid: "tok")

        import subprocess as sp

        fake_completed = sp.CompletedProcess(
            args=["claude"], returncode=2,
            stdout="", stderr="oh no",
        )
        monkeypatch.setattr(wf, "_run_cli_with_heartbeat", lambda cmd, **kw: fake_completed)

        out = wf._execute_claude_chat(
            _make_input(platform="claude_code"), session_dir=str(tmp_path),
        )
        assert out.success is False
        assert "exit 2" in out.error
        assert "oh no" in out.error

    def test_empty_stdout_returns_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wf, "_fetch_claude_token", lambda tid: "tok")
        import subprocess as sp
        fake = sp.CompletedProcess(args=["claude"], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(wf, "_run_cli_with_heartbeat", lambda cmd, **kw: fake)
        out = wf._execute_claude_chat(_make_input(platform="claude_code"), session_dir=str(tmp_path))
        assert out.success is False
        assert "no output" in out.error.lower()

    def test_non_json_stdout_returned_as_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wf, "_fetch_claude_token", lambda tid: "tok")
        import subprocess as sp
        fake = sp.CompletedProcess(
            args=["claude"], returncode=0, stdout="plain text response", stderr="",
        )
        monkeypatch.setattr(wf, "_run_cli_with_heartbeat", lambda cmd, **kw: fake)
        out = wf._execute_claude_chat(_make_input(platform="claude_code"), session_dir=str(tmp_path))
        assert out.success is True
        assert out.response_text == "plain text response"
        assert out.metadata["platform"] == "claude_code"
