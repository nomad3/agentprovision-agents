"""PR-D desktop-control contract parity — MCP side (passthrough validation).

MCP is a PASSTHROUGH of the API's display-safe payload — it owns no schema. These
tests assert the shared golden fixtures stay display-safe (raw content can never
transit the tool) and that every action the MCP tool can emit is a valid contract
action. The MCP-tool tie-in is import-guarded so the fixture checks run anywhere.

Scope: contract/parity only. No native actuation; read-only over fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _fixtures_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "docs" / "contracts" / "desktop-control"
        if cand.is_dir():
            return cand
    raise AssertionError("docs/contracts/desktop-control not found above this test")


FIXTURES = _fixtures_dir()
CLAIM = "pointer_command_claim.display_safe.json"
DENY_BUNDLE = "deny.missing_target_bundle_id.json"
DENY_CAP = "deny.capability_mismatch.json"

FORBIDDEN_KEYS = {
    "window_title", "screenshot", "screenshot_b64", "screenshot_bytes",
    "clipboard", "clipboard_text", "ocr_text", "ax_tree", "page_text",
    "signature", "private_key", "raw_title", "title",
}

CONTRACT_ACTIONS = {
    "capture_screenshot", "get_active_app", "read_clipboard",
    "pointer_move", "pointer_click", "keyboard_type", "keyboard_key_chord",
    "background_app_control_dry_run",
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _forbidden_hits(node, path="") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(_forbidden_hits(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits.extend(_forbidden_hits(value, f"{path}[{i}]"))
    return hits


@pytest.mark.parametrize("name", [CLAIM, DENY_BUNDLE, DENY_CAP])
def test_passthrough_is_display_safe(name):
    hits = _forbidden_hits(_load(name))
    assert hits == [], f"{name} would leak raw field(s) through MCP passthrough: {hits}"


@pytest.mark.parametrize("name", [DENY_BUNDLE, DENY_CAP])
def test_deny_shape_conventions(name):
    d = _load(name)
    # The MCP observation tools return exactly these denial conventions today.
    assert d["status"] == "denied"
    assert d["down_channel_available"] is False
    assert d["action"] in CONTRACT_ACTIONS
    assert "screenshot" not in d and "clipboard_text" not in d
    assert d["code"]  # stable typed denial code (PR-C)


def test_mcp_tool_actions_are_valid_contract_actions():
    dc = pytest.importorskip("src.mcp_tools.desktop_control")
    # Every action the MCP surface can emit must be a known contract action.
    assert set(dc._TOOL_ACTIONS.values()).issubset(CONTRACT_ACTIONS)
