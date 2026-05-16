"""Tests for the *_prepare_*_home filesystem helpers in workflows.py.

These functions materialise per-tenant CLI home directories (.codex/,
.gemini/) with the right config files. They have no external dependencies
beyond the filesystem so they're pure-function-ish targets for testing.
"""
from __future__ import annotations

import json
import os

import workflows as wf


# ── _prepare_codex_home ─────────────────────────────────────────────────

class TestPrepareCodexHome:
    def test_writes_auth_json_and_config_toml(self, tmp_path, fake_mcp_config_json):
        session_dir = str(tmp_path / "tenant-aaa")
        os.makedirs(session_dir)

        out_home = wf._prepare_codex_home(
            session_dir=session_dir,
            auth_payload={"OPENAI_API_KEY": "sk-fake"},
            mcp_config_json=fake_mcp_config_json,
        )

        assert out_home.endswith(".codex")
        assert os.path.isdir(out_home)

        auth = json.loads((open(os.path.join(out_home, "auth.json"))).read())
        assert auth == {"OPENAI_API_KEY": "sk-fake"}

        cfg_text = open(os.path.join(out_home, "config.toml")).read()
        # Trust line for both /workspace and the session_dir.
        assert 'trust_level = "trusted"' in cfg_text
        # MCP config emitted.
        assert "[mcp_servers.agentprovision]" in cfg_text
        assert "[mcp_servers.github]" in cfg_text

    def test_skips_mcp_config_when_empty(self, tmp_path):
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_codex_home(session_dir, {"k": "v"}, "")
        cfg = open(os.path.join(home, "config.toml")).read()
        assert "[mcp_servers" not in cfg

    def test_emits_rmcp_opt_in_when_mcp_config_present(
        self, tmp_path, fake_mcp_config_json
    ):
        """2026-05-16 fix: Codex CLI silently ignores SSE/streamable_http
        MCP servers unless the top-level
        ``experimental_use_rmcp_client = true`` flag is set in
        ``config.toml``. The flag MUST appear before any ``[section]``
        header (TOML grammar requires top-level keys precede sections).
        See docs/plans/2026-05-16-codex-mcp-tool-access-fix.md."""
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_codex_home(
            session_dir, {"OPENAI_API_KEY": "sk"}, fake_mcp_config_json
        )
        cfg = open(os.path.join(home, "config.toml")).read()
        # If the flag appeared after a `[section]` header, TOML would
        # parse it as a key of that section and Codex would silently
        # ignore the opt-in — the `startswith` assertion is the only
        # way to catch this.
        assert cfg.startswith("experimental_use_rmcp_client = true")
        # Sanity: the MCP block is still emitted below the flag.
        assert "[mcp_servers.agentprovision]" in cfg

    def test_omits_rmcp_opt_in_when_mcp_config_empty(self, tmp_path):
        """Empty mcp_config_json means there's nothing for the rmcp
        client to talk to — emitting the opt-in would just be noise
        (and is also the contract the standalone code-execution
        callsite in ``_execute_codex_code_task`` relies on staying a
        no-op)."""
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_codex_home(session_dir, {"k": "v"}, "")
        cfg = open(os.path.join(home, "config.toml")).read()
        assert "experimental_use_rmcp_client" not in cfg

    def test_codex_mcp_emits_http_headers_block(self, tmp_path):
        """Headers from mcp_config_json must survive into the materialized
        config.toml so rmcp_client can forward X-Tenant-Id + Authorization
        on every request. Regression guard for the 2026-05-16 plan's open
        risk #3 — if rmcp drops the headers silently, MCP tool calls
        arrive at the api without tenant context and silently 404 or
        cross-tenant, with no log signal."""
        mcp_config = json.dumps({
            "mcpServers": {
                "agentprovision": {
                    "type": "sse",
                    "url": "http://mcp-tools:8086/sse",
                    "headers": {
                        "X-Tenant-Id": "abc-123",
                        "X-Internal-Key": "secret",
                        "Authorization": "Bearer tok-xyz",
                    },
                },
            },
        })
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_codex_home(
            session_dir, {"OPENAI_API_KEY": "sk"}, mcp_config
        )
        cfg = open(os.path.join(home, "config.toml")).read()
        assert "[mcp_servers.agentprovision]" in cfg
        assert "X-Tenant-Id" in cfg
        assert "Bearer tok-xyz" in cfg
        assert "secret" in cfg

    def test_omits_rmcp_opt_in_when_feature_flag_off(
        self, tmp_path, fake_mcp_config_json, monkeypatch
    ):
        """Rollback lever: setting ``CODEX_USE_RMCP_CLIENT=false``
        suppresses the opt-in even with a non-empty MCP config, so we
        can disable the rmcp_client path via Helm values without a
        code revert if it regresses."""
        monkeypatch.setenv("CODEX_USE_RMCP_CLIENT", "false")
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_codex_home(
            session_dir, {"k": "v"}, fake_mcp_config_json
        )
        cfg = open(os.path.join(home, "config.toml")).read()
        assert "experimental_use_rmcp_client" not in cfg
        # The MCP section is still emitted — only the rmcp opt-in is
        # gated by the flag.
        assert "[mcp_servers.agentprovision]" in cfg


# ── _prepare_gemini_home_apikey ─────────────────────────────────────────

class TestPrepareGeminiHomeApiKey:
    def test_writes_settings_with_api_key_auth(self, tmp_path):
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_gemini_home_apikey(session_dir, "")
        assert home.endswith(".gemini")

        settings = json.loads(open(os.path.join(home, "settings.json")).read())
        assert settings["security"]["auth"]["selectedType"] == "api-key"

        # projects.json bootstrapped (Gemini CLI requires it on first run).
        projects = json.loads(open(os.path.join(home, "projects.json")).read())
        assert projects == {"projects": {}}

    def test_merges_mcp_servers_from_config(self, tmp_path, fake_mcp_config_json):
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_gemini_home_apikey(session_dir, fake_mcp_config_json)
        settings = json.loads(open(os.path.join(home, "settings.json")).read())
        assert "agentprovision" in settings["mcpServers"]
        assert "github" in settings["mcpServers"]

    def test_invalid_mcp_json_does_not_crash(self, tmp_path):
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        home = wf._prepare_gemini_home_apikey(session_dir, "not valid json")
        # mcpServers should be absent (invalid JSON falls through silently).
        settings = json.loads(open(os.path.join(home, "settings.json")).read())
        assert "mcpServers" not in settings


# ── _prepare_gemini_home (OAuth) ────────────────────────────────────────

class TestPrepareGeminiHomeOauth:
    def test_writes_oauth_creds_when_blob_present(self, tmp_path):
        session_dir = str(tmp_path / "t")
        os.makedirs(session_dir)
        oauth_blob = {
            "access_token": "ya29-fake",
            "refresh_token": "1//fake",
            "client_id": "681255809395-x.apps.googleusercontent.com",
        }
        payload = {"oauth_creds": oauth_blob, "email": "user@example.com"}

        home = wf._prepare_gemini_home(session_dir, payload, "")
        assert home.endswith(".gemini")

        oauth_path = os.path.join(home, "oauth_creds.json")
        assert os.path.exists(oauth_path)
        # Must round-trip the blob (preserves Gemini CLI client_id binding).
        assert json.loads(open(oauth_path).read()) == oauth_blob
