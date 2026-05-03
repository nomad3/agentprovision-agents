"""Tests for the persistent SessionManager.

The fully async lifecycle is exercised against mocked ``asyncio.subprocess``
processes — no real ``claude`` binary is ever invoked.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

import session_manager as sm


# ── Module-level constants ──────────────────────────────────────────────

class TestModuleConfig:
    def test_api_base_url_resolved_from_env(self):
        assert sm.API_BASE_URL  # always non-empty after conftest setdefault
        assert sm.API_INTERNAL_KEY

    def test_idle_timeout_and_max_sessions(self):
        assert sm.SESSION_IDLE_TIMEOUT > 0
        assert sm.MAX_SESSIONS >= 1


# ── SessionConfig dataclass ─────────────────────────────────────────────

class TestSessionConfig:
    def test_defaults(self):
        cfg = sm.SessionConfig()
        assert cfg.claude_md_content == ""
        assert cfg.mcp_config == ""
        assert cfg.oauth_token == ""
        assert cfg.model == ""
        assert cfg.allowed_tools == ""

    def test_overrides(self):
        cfg = sm.SessionConfig(
            claude_md_content="hi",
            mcp_config='{"mcpServers": {}}',
            oauth_token="tok",
            model="claude-sonnet-4",
            allowed_tools="Read,Write",
        )
        assert cfg.model == "claude-sonnet-4"
        assert cfg.allowed_tools == "Read,Write"


# ── _build_allowed_tools ────────────────────────────────────────────────

class TestBuildAllowedTools:
    def test_empty_mcp_config_yields_just_read(self):
        # No MCP servers means no wildcards — just the base "Read" tool.
        cfg = sm.SessionConfig()
        out = sm.SessionManager._build_allowed_tools(cfg)
        assert "Read" in out.split(",")

    def test_each_mcp_server_yields_a_wildcard(self, fake_mcp_config_json):
        cfg = sm.SessionConfig(mcp_config=fake_mcp_config_json)
        out = sm.SessionManager._build_allowed_tools(cfg)
        parts = out.split(",")
        assert "mcp__agentprovision__*" in parts
        assert "mcp__github__*" in parts

    def test_invalid_json_does_not_crash(self):
        cfg = sm.SessionConfig(mcp_config="not json")
        out = sm.SessionManager._build_allowed_tools(cfg)
        assert "mcp__agentprovision__*" in out


# ── get_session_manager singleton ───────────────────────────────────────

class TestGetSessionManager:
    def test_returns_singleton(self, monkeypatch):
        # Reset the module-global so the test is independent of order.
        monkeypatch.setattr(sm, "_manager", None)
        a = sm.get_session_manager()
        b = sm.get_session_manager()
        assert a is b
        assert isinstance(a, sm.SessionManager)


# ── _create_session — must spawn a subprocess and persist files ─────────

class TestCreateSession:
    @pytest.mark.asyncio
    async def test_writes_claude_md_and_mcp_config(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sm, "MAX_SESSIONS", 5)

        # Redirect /tmp/st_sessions into pytest tmp_path so we can inspect it.
        original_join = os.path.join

        def patched_join(*parts):
            if parts[:2] == ("/tmp", "st_sessions"):
                return original_join(str(tmp_path), *parts[2:])
            return original_join(*parts)

        monkeypatch.setattr(sm.os.path, "join", patched_join)

        # Mock asyncio.create_subprocess_exec to avoid spawning a real binary.
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        fake_proc.returncode = None
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = MagicMock()
        fake_proc.terminate = MagicMock()
        fake_proc.kill = MagicMock()
        fake_proc.wait = AsyncMock(return_value=0)

        async def fake_create(*args, **kwargs):
            return fake_proc

        monkeypatch.setattr(sm.asyncio, "create_subprocess_exec", fake_create)

        manager = sm.SessionManager()
        cfg = sm.SessionConfig(
            claude_md_content="# CLAUDE.md\nProject context",
            mcp_config='{"mcpServers": {"agentprovision": {}}}',
            oauth_token="oat-FAKE-1",
        )

        session = await manager._create_session("tenant-aaa", cfg)

        assert session is not None
        assert session.tenant_id == "tenant-aaa"
        assert session.process is fake_proc

        session_dir = tmp_path / "tenant-aaa"
        assert (session_dir / "CLAUDE.md").read_text().startswith("# CLAUDE.md")
        assert json.loads((session_dir / "mcp.json").read_text())["mcpServers"]

    @pytest.mark.asyncio
    async def test_subprocess_failure_returns_none(self, monkeypatch, tmp_path):
        original_join = os.path.join

        def patched_join(*parts):
            if parts[:2] == ("/tmp", "st_sessions"):
                return original_join(str(tmp_path), *parts[2:])
            return original_join(*parts)

        monkeypatch.setattr(sm.os.path, "join", patched_join)

        async def boom(*a, **kw):
            raise OSError("claude not found")

        monkeypatch.setattr(sm.asyncio, "create_subprocess_exec", boom)
        manager = sm.SessionManager()
        out = await manager._create_session("tenant-bbb", sm.SessionConfig())
        assert out is None

    @pytest.mark.asyncio
    async def test_oauth_token_passed_via_env(self, monkeypatch, tmp_path):
        original_join = os.path.join

        def patched_join(*parts):
            if parts[:2] == ("/tmp", "st_sessions"):
                return original_join(str(tmp_path), *parts[2:])
            return original_join(*parts)

        monkeypatch.setattr(sm.os.path, "join", patched_join)

        captured: dict = {}

        async def fake_create(*args, **kwargs):
            captured["env"] = kwargs.get("env") or {}
            captured["cmd"] = args
            proc = MagicMock()
            proc.pid = 999
            proc.returncode = None
            proc.stdin = MagicMock()
            proc.stdout = MagicMock()
            return proc

        monkeypatch.setattr(sm.asyncio, "create_subprocess_exec", fake_create)

        manager = sm.SessionManager()
        await manager._create_session(
            "tenant-ccc",
            sm.SessionConfig(oauth_token="oat-secret-zzz"),
        )

        assert captured["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oat-secret-zzz"
        # Command shape sanity — must include claude + stream-json formats.
        cmd = captured["cmd"]
        assert cmd[0] == "claude"
        assert "--input-format" in cmd
        assert "stream-json" in cmd


# ── _kill_session — robust against double-kill / dead process ──────────

class TestKillSession:
    @pytest.mark.asyncio
    async def test_kill_unknown_tenant_is_noop(self):
        manager = sm.SessionManager()
        await manager._kill_session("does-not-exist")  # must not raise

    @pytest.mark.asyncio
    async def test_kill_terminates_live_process(self):
        manager = sm.SessionManager()
        proc = MagicMock()
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        session = sm.ActiveSession(tenant_id="t-1", session_id="sess", process=proc)
        manager._sessions["t-1"] = session

        await manager._kill_session("t-1")

        proc.terminate.assert_called_once()
        assert "t-1" not in manager._sessions

    @pytest.mark.asyncio
    async def test_kill_sigkills_when_terminate_times_out(self, monkeypatch):
        manager = sm.SessionManager()
        proc = MagicMock()
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        session = sm.ActiveSession(tenant_id="t-1", session_id="sess", process=proc)
        manager._sessions["t-1"] = session

        await manager._kill_session("t-1")
        proc.kill.assert_called_once()


# ── send_message: fast-path returns parsed result ─────────────────────────

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_returns_parsed_result_event(self, monkeypatch):
        manager = sm.SessionManager()

        # Pre-create a fake session so send_message uses the existing branch.
        proc = MagicMock()
        proc.returncode = None
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()

        lines = [
            b'{"type":"assistant_message","content":"thinking"}\n',
            b'{"type":"result","result":"hi back","session_id":"s1","usage":{"input_tokens":3,"output_tokens":5},"model":"claude-x","total_cost_usd":0.0001,"num_turns":1}\n',
        ]
        proc.stdout = MagicMock()
        proc.stdout.readline = AsyncMock(side_effect=lines)

        session = sm.ActiveSession(tenant_id="t-1", session_id="s", process=proc)
        manager._sessions["t-1"] = session

        out = await manager.send_message("t-1", "hello", sm.SessionConfig())
        assert out["success"] is True
        assert out["response_text"] == "hi back"
        assert out["metadata"]["model"] == "claude-x"
        assert out["metadata"]["input_tokens"] == 3

    @pytest.mark.asyncio
    async def test_dead_process_creates_new_session(self, monkeypatch):
        manager = sm.SessionManager()
        # Existing session whose process already exited.
        proc = MagicMock()
        proc.returncode = 1
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        manager._sessions["t-1"] = sm.ActiveSession(
            tenant_id="t-1", session_id="old", process=proc,
        )

        async def fake_create_session(tenant_id, config):
            # Simulate failure for simplicity — exercises the early-return branch.
            return None

        monkeypatch.setattr(manager, "_create_session", fake_create_session)
        out = await manager.send_message("t-1", "hi", sm.SessionConfig())
        assert out["success"] is False
        assert "Failed to create" in out["error"]
