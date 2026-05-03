"""Tests for src.mcp_tools.data.

The four tools wrap a Postgres client. Module ships without
``src.postgres_client`` so the fallback path is the default — we stub
the client factory to inject a recording client.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import data as d


class _StubPGClient:
    def __init__(self, list_tables=None, describe=None, query=None):
        self.list_tables_resp = list_tables or []
        self.describe_resp = describe or {"columns": []}
        self.query_resp = query or {"rows": [], "columns": []}
        self.calls = []

    async def list_tables(self, catalog=None, schema=None):
        self.calls.append(("list_tables", catalog, schema))
        return self.list_tables_resp

    async def describe_table(self, catalog=None, schema=None, table=None):
        self.calls.append(("describe_table", catalog, schema, table))
        return self.describe_resp

    async def query_sql(self, sql=None, limit=None):
        self.calls.append(("query_sql", sql, limit))
        return self.query_resp


# ---------------------------------------------------------------------------
# discover_datasets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_datasets_requires_tenant(mock_ctx):
    out = await d.discover_datasets(tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_discover_datasets_returns_tables(monkeypatch, mock_ctx):
    stub = _StubPGClient(list_tables=[{"name": "customers"}, {"name": "orders"}])
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.discover_datasets(tenant_id="abc-def", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["count"] == 2
    assert out["catalog"] == "tenant_abc_def"
    # ensure dashes converted to underscores
    assert "abc_def" in stub.calls[0][1]


@pytest.mark.asyncio
async def test_discover_datasets_filters_by_search_query(monkeypatch, mock_ctx):
    stub = _StubPGClient(list_tables=[{"name": "customers"}, {"name": "orders"}])
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.discover_datasets(tenant_id="t", search_query="cust", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["datasets"][0]["name"] == "customers"


@pytest.mark.asyncio
async def test_discover_datasets_handles_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def list_tables(self, **kw):
            raise RuntimeError("db down")

    monkeypatch.setattr(d, "_get_postgres_client", lambda: _Boom())
    out = await d.discover_datasets(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# get_dataset_schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_dataset_schema_requires_id(mock_ctx):
    out = await d.get_dataset_schema(dataset_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_get_dataset_schema_validates_format(mock_ctx):
    out = await d.get_dataset_schema(dataset_id="too.few", ctx=mock_ctx)
    assert "Invalid" in out["error"]


@pytest.mark.asyncio
async def test_get_dataset_schema_describe(monkeypatch, mock_ctx):
    stub = _StubPGClient(describe={"columns": [{"name": "id"}]})
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.get_dataset_schema(dataset_id="cat.silver.t1", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["dataset_id"] == "cat.silver.t1"
    assert out["columns"][0]["name"] == "id"
    assert stub.calls[0] == ("describe_table", "cat", "silver", "t1")


@pytest.mark.asyncio
async def test_get_dataset_schema_handles_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def describe_table(self, **kw):
            raise RuntimeError("err")

    monkeypatch.setattr(d, "_get_postgres_client", lambda: _Boom())
    out = await d.get_dataset_schema(dataset_id="a.b.c", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# query_sql
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_sql_requires_sql(mock_ctx):
    out = await d.query_sql(sql="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_query_sql_appends_limit(monkeypatch, mock_ctx):
    stub = _StubPGClient(query={"rows": [{"id": 1}], "columns": ["id"]})
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.query_sql(sql="SELECT * FROM t", limit=50, ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["row_count"] == 1
    sent_sql = stub.calls[0][1]
    assert "LIMIT 50" in sent_sql


@pytest.mark.asyncio
async def test_query_sql_does_not_double_limit(monkeypatch, mock_ctx):
    stub = _StubPGClient(query={"rows": [], "columns": []})
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    await d.query_sql(sql="SELECT * FROM t LIMIT 5", ctx=mock_ctx)
    sent_sql = stub.calls[0][1]
    assert sent_sql.count("LIMIT") == 1


@pytest.mark.asyncio
async def test_query_sql_handles_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def query_sql(self, **kw):
            raise RuntimeError("err")

    monkeypatch.setattr(d, "_get_postgres_client", lambda: _Boom())
    out = await d.query_sql(sql="SELECT 1", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# generate_insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_insights_requires_id(mock_ctx):
    out = await d.generate_insights(dataset_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_insights_uses_focus_areas(monkeypatch, mock_ctx):
    stub = _StubPGClient(query={"rows": [{"total_rows": 100}]})
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.generate_insights(
        dataset_id="cat.silver.t",
        focus_areas="trends, anomalies",
        ctx=mock_ctx,
    )
    assert out["status"] == "success"
    assert out["focus_areas"] == ["trends", "anomalies"]


@pytest.mark.asyncio
async def test_generate_insights_default_focus(monkeypatch, mock_ctx):
    stub = _StubPGClient(query={"rows": []})
    monkeypatch.setattr(d, "_get_postgres_client", lambda: stub)
    out = await d.generate_insights(dataset_id="a.b.c", ctx=mock_ctx)
    assert out["focus_areas"] == ["general"]


@pytest.mark.asyncio
async def test_generate_insights_handles_exception(monkeypatch, mock_ctx):
    class _Boom:
        async def query_sql(self, **kw):
            raise RuntimeError("err")

    monkeypatch.setattr(d, "_get_postgres_client", lambda: _Boom())
    out = await d.generate_insights(dataset_id="a.b.c", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# _get_postgres_client fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_postgres_client_fallback_returns_error_dict():
    client = d._get_postgres_client()
    out = await client.query_sql("SELECT 1")
    assert "error" in out
    assert (await client.list_tables(catalog="x", schema="y")) == []
    assert "error" in (await client.describe_table(catalog="x", schema="y", table="z"))
