"""Tests for src.mcp_tools.reports.

Two tools — ``extract_document_data`` (pure schema return) and
``generate_excel_report`` (httpx POST). The first has no I/O, the
second calls /api/v1/reports/internal/generate.
"""
from __future__ import annotations

import json
import pytest

from src.mcp_tools import reports as rp


# ---------------------------------------------------------------------------
# extract_document_data — pure logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_document_data_returns_schema(mock_ctx):
    out = await rp.extract_document_data(
        file_text="Sample text",
        filename="report.pdf",
        ctx=mock_ctx,
    )
    assert out["status"] == "schema_provided"
    assert out["filename"] == "report.pdf"
    assert out["document_type"] == "auto"
    assert "practice_name" in out["target_schema"]
    assert "Provider Classification" in out["instructions"]
    assert out["file_preview"] == "Sample text"


@pytest.mark.asyncio
async def test_extract_document_data_truncates_preview(mock_ctx):
    long_text = "x" * 5000
    out = await rp.extract_document_data(
        file_text=long_text, filename="x.pdf", ctx=mock_ctx
    )
    assert len(out["file_preview"]) == 3000


@pytest.mark.asyncio
async def test_extract_document_data_requires_text(mock_ctx):
    out = await rp.extract_document_data(file_text="", filename="x.pdf", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# generate_excel_report
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_httpx(monkeypatch, make_client):
    def _install(default_status=200, default_json=None, side_effect=None):
        client = make_client(
            default_status=default_status,
            default_json=default_json,
            side_effect=side_effect,
        )
        monkeypatch.setattr(rp.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_generate_excel_requires_tenant(mock_ctx):
    out = await rp.generate_excel_report(report_data="{}", tenant_id="", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_excel_requires_data(mock_ctx):
    out = await rp.generate_excel_report(report_data="", tenant_id="t", ctx=mock_ctx)
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_excel_validates_json(mock_ctx):
    out = await rp.generate_excel_report(report_data="not-json", tenant_id="t", ctx=mock_ctx)
    assert "Invalid JSON" in out["error"]


@pytest.mark.asyncio
async def test_generate_excel_validates_required_fields(mock_ctx):
    out = await rp.generate_excel_report(
        report_data='{"practice_name": "Acme"}', tenant_id="t", ctx=mock_ctx
    )
    assert "Missing" in out["error"]
    assert "report_period" in out["error"]


@pytest.mark.asyncio
async def test_generate_excel_happy_path(patch_httpx, mock_ctx, patch_settings):
    client = patch_httpx(
        default_status=200,
        default_json={
            "download_url": "/files/x.xlsx",
            "filename": "x.xlsx",
            "file_id": "f-1",
            "message": "ok",
        },
    )
    body = {"practice_name": "Acme", "report_period": "Jun 2026", "providers": []}
    out = await rp.generate_excel_report(
        report_data=json.dumps(body), tenant_id="t", ctx=mock_ctx
    )
    assert out["status"] == "success"
    assert out["download_url"] == "/files/x.xlsx"
    sent = client.calls[0]
    assert sent["headers"]["X-Tenant-ID"] == "t"
    assert sent["json"]["practice_name"] == "Acme"


@pytest.mark.asyncio
async def test_generate_excel_propagates_http_error(patch_httpx, mock_ctx, patch_settings):
    patch_httpx(default_status=500, default_json={})
    body = {"practice_name": "Acme", "report_period": "x"}
    out = await rp.generate_excel_report(
        report_data=json.dumps(body), tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_generate_excel_handles_network_exception(monkeypatch, mock_ctx, patch_settings):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rp.httpx, "AsyncClient", lambda *a, **kw: _Boom())
    body = {"practice_name": "Acme", "report_period": "x"}
    out = await rp.generate_excel_report(
        report_data=json.dumps(body), tenant_id="t", ctx=mock_ctx
    )
    assert "error" in out
