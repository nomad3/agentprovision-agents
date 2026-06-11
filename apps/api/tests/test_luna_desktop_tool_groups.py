"""Tests for migration 175 — operator Luna gets desktop tool groups."""
from __future__ import annotations

import os

import pytest

SIMON_TENANT_ID = "752626d9-8b2c-4aa2-87ef-c458d48bd38a"
REQUIRED_GROUPS = {"desktop_observe", "desktop_control"}


@pytest.mark.integration
def test_operator_luna_agents_include_desktop_tool_groups():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or not db_url.startswith(("postgresql", "postgres")):
        pytest.skip("DATABASE_URL not pointing at Postgres — integration only")

    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    with engine.connect() as c:
        applied = c.execute(text(
            "SELECT 1 FROM _migrations WHERE filename = "
            "'175_luna_operator_desktop_tool_groups.sql'"
        )).scalar()
        assert applied, (
            "migration 175_luna_operator_desktop_tool_groups.sql not in "
            "_migrations — apply it before running this test"
        )

        rows = c.execute(text(
            "SELECT name, tool_groups FROM agents "
            "WHERE tenant_id = :tenant_id AND name IN ('Luna', 'Luna Supervisor')"
        ), {"tenant_id": SIMON_TENANT_ID}).fetchall()

    by_name = {row[0]: set(row[1] or []) for row in rows}
    assert {"Luna", "Luna Supervisor"}.issubset(by_name), (
        f"operator Luna rows missing after migration 175: {sorted(by_name)}"
    )
    for name, groups in by_name.items():
        missing = REQUIRED_GROUPS - groups
        assert not missing, f"{name}.tool_groups missing {sorted(missing)}"
