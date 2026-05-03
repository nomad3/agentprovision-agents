"""Tests for src.mcp_tools.shell.

Two tools — execute_shell and deploy_changes — that wrap subprocess.run.
We stub _run_shell so no real shell command is invoked.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import shell as sh


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

def test_truncate_short_string_unchanged():
    assert sh._truncate("hi", 100) == "hi"


def test_truncate_long_string_appended_notice():
    out = sh._truncate("a" * 500, 100)
    assert "truncated" in out
    assert len(out.encode()) > 100  # because of the notice
    assert out.startswith("a" * 100)


# ---------------------------------------------------------------------------
# _run_shell — exercise the real subprocess for a deterministic command
# ---------------------------------------------------------------------------

def test_run_shell_returncode_and_stdout(tmp_path):
    out = sh._run_shell("echo hello", str(tmp_path), 5)
    assert out["return_code"] == 0
    assert "hello" in out["stdout"]


def test_run_shell_timeout(tmp_path):
    out = sh._run_shell("sleep 5", str(tmp_path), 1)
    # subprocess.TimeoutExpired branch
    assert out["return_code"] == -1
    assert "timed out" in out["stderr"]


# ---------------------------------------------------------------------------
# execute_shell
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_shell_requires_command(mock_ctx):
    out = await sh.execute_shell(command="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_execute_shell_clamps_timeout(monkeypatch, mock_ctx):
    captured = {}

    def _fake_run(cmd, wd, timeout):
        captured["timeout"] = timeout
        return {"stdout": "", "stderr": "", "return_code": 0, "command": cmd}

    monkeypatch.setattr(sh, "_run_shell", _fake_run)

    await sh.execute_shell(command="ls", timeout=99999, ctx=mock_ctx)
    assert captured["timeout"] == sh._MAX_TIMEOUT

    await sh.execute_shell(command="ls", timeout=0, ctx=mock_ctx)
    assert captured["timeout"] == 1


@pytest.mark.asyncio
async def test_execute_shell_returns_run_result(monkeypatch, mock_ctx):
    def _fake_run(cmd, wd, timeout):
        return {"stdout": "hi", "stderr": "", "return_code": 0, "command": cmd}

    monkeypatch.setattr(sh, "_run_shell", _fake_run)
    out = await sh.execute_shell(command="echo hi", ctx=mock_ctx)
    assert out["stdout"] == "hi"


@pytest.mark.asyncio
async def test_execute_shell_logs_warning_on_nonzero(monkeypatch, mock_ctx):
    def _fake_run(cmd, wd, timeout):
        return {"stdout": "", "stderr": "boom", "return_code": 1, "command": cmd}

    monkeypatch.setattr(sh, "_run_shell", _fake_run)
    out = await sh.execute_shell(command="false", ctx=mock_ctx)
    assert out["return_code"] == 1


# ---------------------------------------------------------------------------
# deploy_changes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deploy_changes_requires_message(mock_ctx):
    out = await sh.deploy_changes(commit_message="", ctx=mock_ctx)
    assert "error" in out


def _stage_calls(commands):
    """Return a side-effect function that returns scripted results."""
    queue = list(commands)

    def _fake_run(cmd, wd, timeout):
        if not queue:
            return {"stdout": "", "stderr": "", "return_code": 0, "command": cmd}
        return queue.pop(0)

    return _fake_run


@pytest.mark.asyncio
async def test_deploy_changes_nothing_to_commit(monkeypatch, mock_ctx):
    """When there are no staged changes, the diff returns empty."""
    sequence = [
        {"stdout": "", "stderr": "", "return_code": 0, "command": "git add -A"},
        {"stdout": "", "stderr": "", "return_code": 0, "command": "git diff"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="x", ctx=mock_ctx)
    assert out["status"] == "nothing_to_commit"


@pytest.mark.asyncio
async def test_deploy_changes_full_happy_path(monkeypatch, mock_ctx):
    sequence = [
        {"stdout": "", "stderr": "", "return_code": 0, "command": "git add -A"},
        {"stdout": "a.py\nb.py", "stderr": "", "return_code": 0, "command": "git diff"},
        {"stdout": "", "stderr": "", "return_code": 0, "command": "git commit"},
        {"stdout": "abc1234", "stderr": "", "return_code": 0, "command": "git rev-parse"},
        {"stdout": "", "stderr": "", "return_code": 0, "command": "git push"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="msg", ctx=mock_ctx)
    assert out["status"] == "pushed"
    assert out["commit_sha"] == "abc1234"
    assert "a.py" in out["files_changed"]


@pytest.mark.asyncio
async def test_deploy_changes_stage_failure_specific_files(monkeypatch, mock_ctx):
    sequence = [
        {"stdout": "", "stderr": "could not stage", "return_code": 1, "command": "git add a.py"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="m", files="a.py", ctx=mock_ctx)
    assert out["status"] == "error"
    assert out["step"] == "stage"


@pytest.mark.asyncio
async def test_deploy_changes_stage_failure_all(monkeypatch, mock_ctx):
    sequence = [
        {"stdout": "", "stderr": "fail", "return_code": 1, "command": "git add -A"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="m", ctx=mock_ctx)
    assert out["status"] == "error"
    assert out["step"] == "stage"


@pytest.mark.asyncio
async def test_deploy_changes_commit_failure(monkeypatch, mock_ctx):
    sequence = [
        {"stdout": "", "stderr": "", "return_code": 0, "command": "stage"},
        {"stdout": "a.py", "stderr": "", "return_code": 0, "command": "diff"},
        {"stdout": "", "stderr": "commit fail", "return_code": 1, "command": "commit"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="m", ctx=mock_ctx)
    assert out["status"] == "error"
    assert out["step"] == "commit"


@pytest.mark.asyncio
async def test_deploy_changes_push_failure(monkeypatch, mock_ctx):
    sequence = [
        {"stdout": "", "stderr": "", "return_code": 0, "command": "stage"},
        {"stdout": "a.py", "stderr": "", "return_code": 0, "command": "diff"},
        {"stdout": "", "stderr": "", "return_code": 0, "command": "commit"},
        {"stdout": "abc", "stderr": "", "return_code": 0, "command": "rev-parse"},
        {"stdout": "", "stderr": "push rejected", "return_code": 1, "command": "push"},
    ]
    monkeypatch.setattr(sh, "_run_shell", _stage_calls(sequence))
    out = await sh.deploy_changes(commit_message="m", ctx=mock_ctx)
    assert out["status"] == "error"
    assert out["step"] == "push"
    assert out["commit_sha"] == "abc"
