"""Tests for migration 165 — Luna gains the `commitments` tool_group.

The Accountable Learning & Commitment System (plan 2026-06-08) registered
the commitment/learning-artifact MCP tools, but agents only receive tools
whose group is in `agent.tool_groups` (resolve_tool_names → CLI
--allowedTools, enforced again by the code-worker hook). Without a
`commitments` group wired to Luna she can *see* her open commitments in
recalled context but has no tool to create/complete them — so "Luna is the
lead / drives it" (plan north star) does not actually hold.

Three layers, mirroring test_luna_learning_tool_group.py:
  1. The `commitments` group exists in the registry and resolves to the
     five MCP tool names (pure, unit).
  2. The bundled luna/skill.md frontmatter lists `commitments` (file-only).
  3. After migration 165, Luna's DB row carries `commitments` (integration).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

from app.services.tool_groups import TOOL_GROUPS, resolve_tool_names

REPO_ROOT = Path(__file__).resolve().parents[3]
LUNA_SKILL_PATH = REPO_ROOT / "apps/api/app/agents/_bundled/luna/skill.md"
SIMON_TENANT_ID = "752626d9-8b2c-4aa2-87ef-c458d48bd38a"

EXPECTED_COMMITMENT_TOOLS = {
    "commitment_create",
    "commitment_complete",
    "commitment_list_open",
    "commitment_scan_red_flags",
    "learning_artifact_write",
}


def _load_luna_frontmatter() -> dict:
    content = LUNA_SKILL_PATH.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert match, f"Luna skill.md missing YAML frontmatter: {LUNA_SKILL_PATH}"
    return yaml.safe_load(match.group(1))


def test_commitments_group_resolves_to_the_five_mcp_tools():
    """The registry exposes a `commitments` group → the 5 commitment MCP tools."""
    assert "commitments" in TOOL_GROUPS, (
        "TOOL_GROUPS missing `commitments` — the drive-surface tools are "
        "unreachable from any agent's CLI allowlist"
    )
    resolved = set(resolve_tool_names(["commitments"]) or [])
    assert resolved == EXPECTED_COMMITMENT_TOOLS, (
        f"commitments group resolved to {sorted(resolved)}, "
        f"expected {sorted(EXPECTED_COMMITMENT_TOOLS)}"
    )


def test_luna_skill_md_frontmatter_includes_commitments_group():
    """Bundled luna/skill.md must declare `commitments` so new Luna agents
    get the drive surface (file half of Luna's effective tool_groups)."""
    fm = _load_luna_frontmatter()
    declared = set(fm.get("tool_groups", []))
    assert "commitments" in declared, (
        f"luna/skill.md tool_groups missing `commitments`: {sorted(declared)}"
    )


@pytest.mark.integration
def test_luna_db_row_includes_commitments_after_migration_165():
    """After migration 165, Luna on Simon's tenant has `commitments` in its
    tool_groups jsonb array. Skipped in unit-mode (no Postgres DATABASE_URL)."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or not db_url.startswith(("postgresql", "postgres")):
        pytest.skip("DATABASE_URL not pointing at Postgres — integration only")

    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    with engine.connect() as c:
        applied = c.execute(text(
            "SELECT 1 FROM _migrations WHERE filename = "
            "'165_luna_add_commitments_tool_group.sql'"
        )).scalar()
        assert applied, (
            "migration 165_luna_add_commitments_tool_group.sql not in "
            "_migrations — apply it before running this test"
        )
        rows = c.execute(text(
            "SELECT name, tool_groups FROM agents "
            "WHERE name ILIKE '%luna%' AND tenant_id = :tid"
        ), {"tid": SIMON_TENANT_ID}).fetchall()

    assert rows, f"No Luna agents on tenant {SIMON_TENANT_ID}"
    for name, tool_groups in rows:
        assert isinstance(tool_groups, list), (
            f"{name}: tool_groups not a list: {type(tool_groups).__name__}"
        )
        assert "commitments" in tool_groups, (
            f"{name}.tool_groups missing `commitments` after migration 165: "
            f"{tool_groups}"
        )
