"""Tests for src.mcp_tools.knowledge pure helpers + tenant guards.

The knowledge module uses asyncpg directly and requires a Postgres
connection for the bulk of its tools — these are out of scope for
unit tests. We exercise the pure helpers and the early-exit error
paths so the module isn't a 0% black box.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from src.mcp_tools import knowledge as kn


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------

def test_parse_json_passes_through_dicts_lists():
    assert kn._parse_json({"a": 1}) == {"a": 1}
    assert kn._parse_json([1, 2]) == [1, 2]


def test_parse_json_decodes_string():
    assert kn._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_default_for_invalid():
    assert kn._parse_json("garbage", default=[]) == []


def test_parse_json_default_for_none():
    assert kn._parse_json(None, default={"x": 1}) == {"x": 1}


# ---------------------------------------------------------------------------
# _serialize_row
# ---------------------------------------------------------------------------

class _FakeRow:
    """Quack like asyncpg.Record — supports dict() conversion."""

    def __init__(self, mapping):
        self._m = dict(mapping)

    def keys(self):
        return self._m.keys()

    def __iter__(self):
        return iter(self._m)

    def __getitem__(self, k):
        return self._m[k]


def test_serialize_row_handles_uuid_datetime_decimal():
    u = uuid.uuid4()
    dt = datetime(2026, 5, 3, 12, 0, 0)
    out = kn._serialize_row(_FakeRow({
        "id": u,
        "created": dt,
        "amount": Decimal("12.50"),
        "name": "x",
    }))
    assert out["id"] == str(u)
    assert out["created"].startswith("2026-05-03")
    assert out["amount"] == 12.50
    assert out["name"] == "x"


# ---------------------------------------------------------------------------
# _get_db_url normalization
# ---------------------------------------------------------------------------

def test_get_db_url_strips_async_driver(monkeypatch):
    """Cover the DSN normalization: strip the SQLAlchemy ``+asyncpg``
    suffix so asyncpg accepts the URL."""
    from src import config as cfg

    monkeypatch.setattr(
        cfg.settings, "DATABASE_URL",
        "postgresql+asyncpg://u:p@h/db", raising=False,
    )
    out = kn._get_db_url()
    assert out.startswith("postgresql://")
    assert "+asyncpg" not in out


def test_get_db_url_falls_back_to_env(monkeypatch):
    from src import config as cfg

    monkeypatch.setattr(cfg.settings, "DATABASE_URL", "", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")
    out = kn._get_db_url()
    assert out.startswith("postgresql://")
