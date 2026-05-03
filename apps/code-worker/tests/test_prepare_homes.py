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
