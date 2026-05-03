"""Tests for src.mcp_tools.analytics.

Three tools — calculate (pure logic), compare_periods, forecast — plus
helpers _parse_json and _get_postgres_client. The Postgres-bound tools
are tested with a stub client that records the executed SQL.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import analytics as an


# ---------------------------------------------------------------------------
# calculate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calculate_happy_path():
    out = await an.calculate("100 * 1.15")
    assert out["status"] == "success"
    assert out["result"] == pytest.approx(115.0)


@pytest.mark.asyncio
async def test_calculate_complex():
    out = await an.calculate("(500 - 300) / 200")
    assert out["result"] == 1.0


@pytest.mark.asyncio
async def test_calculate_rejects_empty():
    out = await an.calculate("")
    assert "error" in out


@pytest.mark.asyncio
async def test_calculate_rejects_disallowed_chars():
    out = await an.calculate("__import__('os').system('ls')")
    assert "Invalid characters" in out["error"]


@pytest.mark.asyncio
async def test_calculate_rejects_letters():
    out = await an.calculate("100 + abc")
    assert "Invalid characters" in out["error"]


@pytest.mark.asyncio
async def test_calculate_handles_division_by_zero():
    out = await an.calculate("100 / 0")
    assert "error" in out


# ---------------------------------------------------------------------------
# _parse_json helper
# ---------------------------------------------------------------------------

def test_parse_json_passes_through_objects():
    assert an._parse_json({"a": 1}) == {"a": 1}
    assert an._parse_json([1, 2]) == [1, 2]


def test_parse_json_decodes_strings():
    assert an._parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_returns_default_for_invalid():
    assert an._parse_json("not-json", default={}) == {}


def test_parse_json_returns_default_for_none():
    assert an._parse_json(None, default=[]) == []


# ---------------------------------------------------------------------------
# _get_postgres_client fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_postgres_client_fallback_returns_error_dict():
    """Module ships without ``src.postgres_client`` so we always hit the
    fallback path. The fallback returns a friendly error rather than
    raising."""
    client = an._get_postgres_client()
    out = await client.query_sql("SELECT 1")
    assert "error" in out


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------

class _StubPGClient:
    def __init__(self, rows):
        self._rows = rows
        self.last_sql = None

    async def query_sql(self, sql, **kwargs):
        self.last_sql = sql
        return {"rows": self._rows}


@pytest.mark.asyncio
async def test_compare_periods_validates_required(mock_ctx):
    out = await an.compare_periods(dataset_id="", metric="m", period1="{}", period2="{}", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_compare_periods_returns_comparison(monkeypatch, mock_ctx):
    stub = _StubPGClient([{"period1_total": 100, "period2_total": 150, "absolute_change": 50}])
    monkeypatch.setattr(an, "_get_postgres_client", lambda: stub)

    out = await an.compare_periods(
        dataset_id="t.s.tbl",
        metric="revenue",
        period1='{"start": "2024-01-01", "end": "2024-03-31"}',
        period2='{"start": "2024-04-01", "end": "2024-06-30"}',
        ctx=mock_ctx,
    )

    assert out["status"] == "success"
    assert out["comparison"]["absolute_change"] == 50
    assert "revenue" in stub.last_sql
    assert "2024-01-01" in stub.last_sql


@pytest.mark.asyncio
async def test_compare_periods_handles_empty_rows(monkeypatch, mock_ctx):
    monkeypatch.setattr(an, "_get_postgres_client", lambda: _StubPGClient([]))
    out = await an.compare_periods(
        dataset_id="t.s.tbl",
        metric="m",
        period1='{"start": "a", "end": "b"}',
        period2='{"start": "c", "end": "d"}',
        ctx=mock_ctx,
    )
    assert out["comparison"] == {}


@pytest.mark.asyncio
async def test_compare_periods_handles_query_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def query_sql(self, sql, **kwargs):
            raise RuntimeError("db gone")

    monkeypatch.setattr(an, "_get_postgres_client", lambda: _Boom())
    out = await an.compare_periods(
        dataset_id="t.s.tbl",
        metric="m",
        period1="{}",
        period2="{}",
        ctx=mock_ctx,
    )
    assert "error" in out


# ---------------------------------------------------------------------------
# forecast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forecast_validates_required(mock_ctx):
    assert "error" in await an.forecast(dataset_id="", target_column="x", time_column="t", ctx=mock_ctx)
    assert "error" in await an.forecast(dataset_id="d", target_column="", time_column="t", ctx=mock_ctx)
    assert "error" in await an.forecast(dataset_id="d", target_column="x", time_column="", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_forecast_returns_historical_data(monkeypatch, mock_ctx):
    stub = _StubPGClient([{"date": "2026-05-01", "revenue": 100, "moving_avg": 95}])
    monkeypatch.setattr(an, "_get_postgres_client", lambda: stub)

    out = await an.forecast(
        dataset_id="t.s.tbl",
        target_column="revenue",
        time_column="date",
        horizon=14,
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["target"] == "revenue"
    assert out["horizon"] == 14
    assert len(out["historical_data"]) == 1


@pytest.mark.asyncio
async def test_forecast_handles_query_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def query_sql(self, sql, **kwargs):
            raise RuntimeError("db gone")

    monkeypatch.setattr(an, "_get_postgres_client", lambda: _Boom())
    out = await an.forecast(dataset_id="d", target_column="x", time_column="t", ctx=mock_ctx)
    assert "error" in out
