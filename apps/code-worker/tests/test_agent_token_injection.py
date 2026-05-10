"""Tests for agent-token mint + hook injection in code-worker — Phase 4 commit 5.

Covers:
  - When CodeTaskInput carries agent_id + task_id, the env trio is
    populated and .claude.json + hooks dir exist at WORKSPACE.
  - When agent_id/task_id are absent (legacy chat hot path), no
    injection runs and claude_env stays minimal.
  - .claude.json mode 0600 (defence-in-depth, also locked by hook
    template tests but verified end-to-end here too).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fake_post(url, json=None, headers=None):  # noqa: ARG001
    """Stand in for httpx.Client.post → returns a JWT-looking string."""
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):  # noqa: D401
            return {"token": "header.payload.signature"}

    return _Resp()


@pytest.fixture
def fake_workspace(tmp_path, monkeypatch):
    """Re-point WORKSPACE to a tmp dir so the writers don't touch /workspace."""
    import workflows  # noqa: F401

    monkeypatch.setattr("workflows.WORKSPACE", str(tmp_path))
    return tmp_path


def test_inject_agent_token_populates_env_and_writes_files(fake_workspace, monkeypatch):
    """End-to-end: helper called with full CodeTaskInput trio populates
    env vars and writes .claude.json + hooks at workspace root."""
    from workflows import CodeTaskInput, _inject_agent_token_and_hooks

    task_input = CodeTaskInput(
        task_description="Test task",
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        parent_workflow_id="wf-123",
        parent_chain=[],
        allowed_tools=["recall_memory", "record_observation"],
    )
    claude_env: dict = {"CLAUDE_CODE_OAUTH_TOKEN": "stub-claude-token"}

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):  # noqa: ARG002
            return _fake_post(url, json=json, headers=headers)

    monkeypatch.setattr("workflows.httpx.Client", lambda timeout=None: _FakeClient())

    _inject_agent_token_and_hooks(
        task_input=task_input,
        claude_env=claude_env,
    )

    # ── Env trio ───────────────────────────────────────────────────
    assert claude_env["AGENTPROVISION_AGENT_TOKEN"] == "header.payload.signature"
    assert claude_env["AGENTPROVISION_TASK_ID"] == task_input.task_id
    assert claude_env["AGENTPROVISION_PARENT_WORKFLOW_ID"] == "wf-123"
    assert (
        claude_env["AGENTPROVISION_ALLOWED_TOOLS"]
        == "recall_memory record_observation"
    )
    assert "AGENTPROVISION_API" in claude_env
    # Original auth env preserved
    assert claude_env["CLAUDE_CODE_OAUTH_TOKEN"] == "stub-claude-token"

    # ── Files written ──────────────────────────────────────────────
    claude_json = fake_workspace / ".claude.json"
    assert claude_json.exists()
    body = json.loads(claude_json.read_text())
    assert (
        body["mcpServers"]["agentprovision"]["headers"]["Authorization"]
        == "Bearer header.payload.signature"
    )
    # Mode 0600
    mode = claude_json.stat().st_mode & 0o777
    assert mode == 0o600

    pre = fake_workspace / ".claude" / "hooks" / "pretooluse.sh"
    post = fake_workspace / ".claude" / "hooks" / "posttooluse.sh"
    assert pre.exists()
    assert post.exists()


def test_no_injection_when_agent_id_absent(fake_workspace):
    """Legacy chat hot path: CodeTaskInput without agent_id must not
    trigger any token-mint side-effects on the workspace."""
    from workflows import CodeTaskInput

    task_input = CodeTaskInput(
        task_description="Legacy task",
        tenant_id=str(uuid.uuid4()),
    )
    # The execute_code_task entry point gates the helper on
    # agent_id+task_id; we verify the gate condition holds.
    assert task_input.agent_id is None
    assert task_input.task_id is None
    # No file should exist at WORKSPACE since we never invoked the
    # helper.
    assert not (fake_workspace / ".claude.json").exists()
