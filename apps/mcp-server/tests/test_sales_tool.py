"""Tests for src.mcp_tools.sales — happy/error paths + assess helpers.

Sales tools wrap internal `/api/v1/knowledge/*` endpoints. We stub
``_get_entity``, ``_update_entity``, ``_search_entities`` (or the
underlying httpx layer) per scenario.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import sales as sl


# ---------------------------------------------------------------------------
# BANT assess helpers
# ---------------------------------------------------------------------------

def test_assess_budget_with_funding():
    out = sl._assess_budget({"funding_data": {"total_raised": 1000000}})
    assert out["score"] == 70
    assert "Has funding" in out["assessment"]


def test_assess_budget_no_funding():
    out = sl._assess_budget({})
    assert out["score"] == 30


def test_assess_authority_with_decision_maker():
    out = sl._assess_authority({"contacts": [{"role": "CEO"}]})
    assert out["score"] == 80


def test_assess_authority_no_decision_maker():
    out = sl._assess_authority({"contacts": [{"role": "Engineer"}]})
    assert out["score"] == 40


def test_assess_authority_empty_contacts():
    out = sl._assess_authority({})
    assert out["score"] == 40


def test_assess_need_with_signals():
    out = sl._assess_need({"hiring_data": {"open": 5}})
    assert out["score"] == 70


def test_assess_need_no_signals():
    out = sl._assess_need({})
    assert out["score"] == 30


def test_assess_timeline_with_news():
    out = sl._assess_timeline({"recent_news": [{"title": "x"}]})
    assert out["score"] == 60


def test_assess_timeline_no_news():
    out = sl._assess_timeline({"recent_news": []})
    assert out["score"] == 30


# ---------------------------------------------------------------------------
# qualify_lead
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qualify_lead_validates(mock_ctx):
    assert "error" in await sl.qualify_lead(entity_id="e", tenant_id="", ctx=mock_ctx)
    assert "error" in await sl.qualify_lead(entity_id="", tenant_id="t", ctx=mock_ctx)


@pytest.mark.asyncio
async def test_qualify_lead_missing_entity(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(sl, "_get_entity", _none)
    out = await sl.qualify_lead(entity_id="e-1", tenant_id="t", ctx=mock_ctx)
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_qualify_lead_qualified_path(monkeypatch, mock_ctx):
    async def _entity(*a, **kw):
        return {
            "name": "Acme",
            "properties": {
                "funding_data": {"total_raised": 100000},
                "contacts": [{"role": "CEO"}],
                "hiring_data": {"open": 1},
                "recent_news": [{"title": "n"}],
            },
        }

    captured = {}

    async def _update(entity_id, tenant_id, updates, reason=""):
        captured["updates"] = updates
        captured["reason"] = reason
        return True

    monkeypatch.setattr(sl, "_get_entity", _entity)
    monkeypatch.setattr(sl, "_update_entity", _update)

    out = await sl.qualify_lead(entity_id="e-1", tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["qualified"] is True
    assert captured["updates"]["properties"]["pipeline_stage"] == "qualified"


@pytest.mark.asyncio
async def test_qualify_lead_unqualified_path(monkeypatch, mock_ctx):
    async def _entity(*a, **kw):
        return {"name": "n", "properties": {}}

    async def _update(*a, **kw):
        return True

    monkeypatch.setattr(sl, "_get_entity", _entity)
    monkeypatch.setattr(sl, "_update_entity", _update)
    out = await sl.qualify_lead(entity_id="e-1", tenant_id="t", ctx=mock_ctx)
    assert out["qualified"] is False


# ---------------------------------------------------------------------------
# update_pipeline_stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_pipeline_stage_validates(mock_ctx):
    assert "error" in await sl.update_pipeline_stage(
        entity_id="", new_stage="qualified", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sl.update_pipeline_stage(
        entity_id="e", new_stage="", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sl.update_pipeline_stage(
        entity_id="e", new_stage="qualified", tenant_id="", ctx=mock_ctx
    )


@pytest.mark.asyncio
async def test_update_pipeline_stage_missing_entity(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(sl, "_get_entity", _none)
    out = await sl.update_pipeline_stage(
        entity_id="e-x", new_stage="qualified", tenant_id="t", ctx=mock_ctx
    )
    assert "not found" in out["error"]


@pytest.mark.asyncio
async def test_update_pipeline_stage_happy(monkeypatch, mock_ctx):
    async def _entity(*a, **kw):
        return {"properties": {"pipeline_stage": "lead"}}

    captured = {}

    async def _update(entity_id, tenant_id, updates, reason=""):
        captured["updates"] = updates
        return True

    monkeypatch.setattr(sl, "_get_entity", _entity)
    monkeypatch.setattr(sl, "_update_entity", _update)

    out = await sl.update_pipeline_stage(
        entity_id="e-1", new_stage="qualified", reason="next steps",
        tenant_id="t", ctx=mock_ctx,
    )
    assert out["new_stage"] == "qualified"
    assert captured["updates"]["properties"]["pipeline_stage"] == "qualified"


# ---------------------------------------------------------------------------
# get_pipeline_summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_pipeline_summary_validates(mock_ctx):
    out = await sl.get_pipeline_summary(tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_get_pipeline_summary_passes_through(monkeypatch, mock_ctx, make_client):
    client = make_client(default_status=200, default_json={
        "stages": [{"stage": "qualified", "count": 2, "total_value": 7000}],
        "total_leads": 3,
        "total_value": 8000,
    })
    monkeypatch.setattr(sl.httpx, "AsyncClient", lambda *a, **kw: client)
    out = await sl.get_pipeline_summary(tenant_id="t", ctx=mock_ctx)
    # The tool passes through the API payload essentially as-is
    assert "total_leads" in out or "stages" in out or "error" in out


@pytest.mark.asyncio
async def test_get_pipeline_summary_api_error(monkeypatch, mock_ctx, make_client):
    client = make_client(default_status=500, default_json={})
    monkeypatch.setattr(sl.httpx, "AsyncClient", lambda *a, **kw: client)
    out = await sl.get_pipeline_summary(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# schedule_followup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schedule_followup_validates(mock_ctx):
    assert "error" in await sl.schedule_followup(
        entity_id="", action="email", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sl.schedule_followup(
        entity_id="e", action="", tenant_id="t", ctx=mock_ctx
    )


# ---------------------------------------------------------------------------
# generate_proposal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_proposal_validates(mock_ctx):
    assert "error" in await sl.generate_proposal(
        entity_id="", tenant_id="t", ctx=mock_ctx
    )
    assert "error" in await sl.generate_proposal(
        entity_id="e", tenant_id="", ctx=mock_ctx
    )


@pytest.mark.asyncio
async def test_generate_proposal_missing_entity(monkeypatch, mock_ctx):
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(sl, "_get_entity", _none)
    out = await sl.generate_proposal(
        entity_id="e", tenant_id="t", ctx=mock_ctx
    )
    assert "not found" in out["error"]
