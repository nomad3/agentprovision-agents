"""Tests for ``apps/code-worker/hook_templates.py`` — Phase 4 commit 4.

Covers:
  - Golden snapshot of PreToolUse + PostToolUse rendered output
  - jq-path lockdown: fed real Claude-Code-shaped JSON, the rendered
    PreToolUse template extracts ``tool_name`` correctly (defends
    against the I-A regression where ``.tool_input.tool_name`` would
    have made TOOL="" always)
  - .claude.json writer creates the file with mode 0o600 (SR-4)
  - .claude.json idempotent on rewrite
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# code-worker test fixture — sys.path tweak (mirror of conftest.py if needed)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hook_templates import (  # noqa: E402
    render_posttooluse_hook,
    render_pretooluse_hook,
    write_claude_hooks,
    write_claude_mcp_config,
)


# ── Golden-snapshot tests ────────────────────────────────────────────────


def test_pretooluse_template_golden_snapshot():
    """Golden snapshot — locks the rendered text. If this changes,
    update the test deliberately (and check the jq path didn't regress)."""
    rendered = render_pretooluse_hook()
    # Critical invariants — the lockdown for review I-A and I-B.
    assert 'STDIN=$(cat)' in rendered
    assert "jq -r '.tool_name // \"\"'" in rendered
    # NOT the buggy version
    assert ".tool_input.tool_name" not in rendered
    # Local enforcement, NO network call
    assert "curl" not in rendered
    assert "wget" not in rendered
    # AGENTPROVISION_ALLOWED_TOOLS env-driven
    assert "AGENTPROVISION_ALLOWED_TOOLS" in rendered
    # Fail-closed exit code
    assert "exit 2" in rendered


def test_posttooluse_template_golden_snapshot():
    rendered = render_posttooluse_hook()
    assert 'STDIN=$(cat)' in rendered
    assert "jq -r '.tool_name // \"\"'" in rendered
    assert ".tool_input.tool_name" not in rendered
    # Heartbeat endpoint
    assert "/api/v1/agents/internal/heartbeat" in rendered
    # 2s curl timeout, fire-and-forget
    assert "curl -fsS -m 2" in rendered
    assert "|| true" in rendered
    # Auth header carries the agent token
    assert "Authorization: Bearer" in rendered
    assert "AGENTPROVISION_AGENT_TOKEN" in rendered
    assert "AGENTPROVISION_TASK_ID" in rendered


# ── jq path lockdown — the critical regression test ─────────────────────


def _have_jq() -> bool:
    return shutil.which("jq") is not None and shutil.which("bash") is not None


@pytest.mark.skipif(not _have_jq(), reason="jq + bash required for jq-path lockdown")
def test_pretooluse_jq_path_extracts_tool_name_from_real_claude_payload(tmp_path):
    """SR-9 / Phase 3 review I-A: feed a real Claude-Code-shaped JSON
    payload to the rendered PreToolUse template and assert the jq
    expression extracts ``"Bash"`` not ``""``.
    """
    payload = {
        "session_id": "sess-1",
        "transcript_path": "/tmp/x",
        "cwd": str(tmp_path),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }

    # Render the PreToolUse template into a temp script.
    script = tmp_path / "pretooluse.sh"
    script.write_text(render_pretooluse_hook())
    script.chmod(0o700)

    # Set AGENTPROVISION_ALLOWED_TOOLS so the hook actually evaluates
    # the case statement (otherwise it short-circuits at the empty-env
    # branch and we don't exercise the jq path).
    env = os.environ.copy()
    env["AGENTPROVISION_ALLOWED_TOOLS"] = "Bash Read Write"

    proc = subprocess.run(
        [str(script)],
        input=json.dumps(payload).encode("utf-8"),
        env=env,
        capture_output=True,
        timeout=5,
    )
    # Bash is in the allowlist → exit 0. If the jq path were buggy
    # (.tool_input.tool_name → ""), TOOL="" would NOT match " Bash Read Write "
    # → exit 2.
    assert proc.returncode == 0, (
        f"jq path regressed — TOOL extraction failed. stderr={proc.stderr!r}"
    )


@pytest.mark.skipif(not _have_jq(), reason="jq + bash required for jq-path lockdown")
def test_pretooluse_blocks_when_tool_not_in_allowlist(tmp_path):
    payload = {
        "session_id": "sess-1",
        "hook_event_name": "PreToolUse",
        "tool_name": "ForbiddenTool",
        "tool_input": {},
    }
    script = tmp_path / "pretooluse.sh"
    script.write_text(render_pretooluse_hook())
    script.chmod(0o700)
    env = os.environ.copy()
    env["AGENTPROVISION_ALLOWED_TOOLS"] = "Bash Read"
    proc = subprocess.run(
        [str(script)],
        input=json.dumps(payload).encode("utf-8"),
        env=env,
        capture_output=True,
        timeout=5,
    )
    assert proc.returncode == 2
    assert b"ForbiddenTool" in proc.stderr


# ── Writer tests ─────────────────────────────────────────────────────────


def test_write_claude_hooks_writes_executable_files(tmp_path):
    write_claude_hooks(tmp_path)
    pre = tmp_path / ".claude" / "hooks" / "pretooluse.sh"
    post = tmp_path / ".claude" / "hooks" / "posttooluse.sh"
    hooks_json = tmp_path / ".claude" / "hooks" / "hooks.json"
    assert pre.exists()
    assert post.exists()
    assert hooks_json.exists()
    # Owner has +x
    assert pre.stat().st_mode & stat.S_IXUSR
    assert post.stat().st_mode & stat.S_IXUSR
    # hooks.json registers both events
    data = json.loads(hooks_json.read_text())
    events = {h["event"] for h in data["hooks"]}
    assert events == {"PreToolUse", "PostToolUse"}


def test_write_claude_mcp_config_creates_file_with_mode_0600(tmp_path):
    """SR-4: .claude.json carries the agent_token; mode must be 0600."""
    write_claude_mcp_config(
        workdir=tmp_path,
        agent_token="secret-jwt-token",
        mcp_url="https://mcp.agentprovision.com/sse",
    )
    p = tmp_path / ".claude.json"
    assert p.exists()
    # Mode bits: extract permission portion only.
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    # Content shape
    body = json.loads(p.read_text())
    headers = body["mcpServers"]["agentprovision"]["headers"]
    assert headers["Authorization"] == "Bearer secret-jwt-token"


def test_write_claude_mcp_config_idempotent_rewrite(tmp_path):
    """Re-invoking with a fresh token replaces the file cleanly."""
    write_claude_mcp_config(
        workdir=tmp_path,
        agent_token="token-1",
        mcp_url="https://m1/sse",
    )
    write_claude_mcp_config(
        workdir=tmp_path,
        agent_token="token-2",
        mcp_url="https://m2/sse",
    )
    p = tmp_path / ".claude.json"
    body = json.loads(p.read_text())
    headers = body["mcpServers"]["agentprovision"]["headers"]
    assert headers["Authorization"] == "Bearer token-2"
    assert body["mcpServers"]["agentprovision"]["url"] == "https://m2/sse"
    # Mode preserved on rewrite.
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600
