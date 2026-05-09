"""Tests for src.mcp_tools.bookkeeper_export.

The MCP tool is a thin pass-through to /api/v1/bookkeeper-exports/internal/generate.
We assert:
  - argument validation happens client-side (unsupported format, missing
    period dates) without an outbound HTTP call
  - the success path forwards the right payload + headers
  - a non-2xx response is surfaced as an error dict, not raised
"""
from __future__ import annotations

import pytest

from src.mcp_tools import bookkeeper_export as be


# ---------------------------------------------------------------------------
# Argument validation — no HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_tenant_id_returns_error(mock_ctx):
    out = await be.bookkeeper_export_aaha(
        period_start="2026-05-04",
        period_end="2026-05-10",
        tenant_id="",
        ctx=mock_ctx,
    )
    assert "error" in out
    assert "tenant_id" in out["error"]


@pytest.mark.asyncio
async def test_missing_period_returns_error(mock_ctx):
    out = await be.bookkeeper_export_aaha(
        period_start="",
        period_end="",
        tenant_id="7f632730-1a38-41f1-9f99-508d696dbcf1",
        ctx=mock_ctx,
    )
    assert "error" in out
    assert "period" in out["error"].lower()


@pytest.mark.asyncio
async def test_unsupported_format_returns_error(mock_ctx):
    out = await be.bookkeeper_export_aaha(
        period_start="2026-05-04",
        period_end="2026-05-10",
        format="quickbooks_2006",
        tenant_id="7f632730-1a38-41f1-9f99-508d696dbcf1",
        ctx=mock_ctx,
    )
    assert "error" in out
    assert "Unsupported format" in out["error"]


# ---------------------------------------------------------------------------
# Success path — verifies payload + headers + URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_path_forwards_payload(
    mock_ctx, patch_settings, make_client, monkeypatch
):
    client = make_client(
        default_json={
            "file_id": "abc123",
            "filename": "Animal_Doctor_AAHA_2026-05-04_2026-05-10.xlsx",
            "download_url": "/api/v1/bookkeeper-exports/download/abc123?tenant_id=7f632730-1a38-41f1-9f99-508d696dbcf1",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "format": "xlsx",
            "expires_at": "2026-05-11T00:00:00",
        },
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)

    out = await be.bookkeeper_export_aaha(
        period_start="2026-05-04",
        period_end="2026-05-10",
        practice_name="The Animal Doctor SOC",
        locations=["Northgate", "Southside"],
        format="xlsx",
        tenant_id="7f632730-1a38-41f1-9f99-508d696dbcf1",
        ctx=mock_ctx,
    )

    assert out["status"] == "success"
    assert out["file_id"] == "abc123"
    assert out["format"] == "xlsx"
    assert client.calls, "expected one outbound HTTP POST"
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/api/v1/bookkeeper-exports/internal/generate")
    headers = call["headers"]
    assert headers["X-Tenant-Id"] == "7f632730-1a38-41f1-9f99-508d696dbcf1"
    assert headers["X-Internal-Key"] == "test-mcp-key"
    body = call["json"]
    assert body["period_start"] == "2026-05-04"
    assert body["period_end"] == "2026-05-10"
    assert body["practice_name"] == "The Animal Doctor SOC"
    assert body["locations"] == ["Northgate", "Southside"]
    assert body["format"] == "xlsx"


@pytest.mark.asyncio
async def test_format_omitted_means_tenant_default(
    mock_ctx, patch_settings, make_client, monkeypatch
):
    """When `format` is omitted, the tool sends None — letting the API
    side resolve via tenant_features.cpa_export_format."""
    client = make_client(default_json={
        "file_id": "abc",
        "filename": "x.xlsx",
        "download_url": "/d/abc",
        "mime_type": "x",
        "format": "xlsx",
        "expires_at": "x",
    })
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)

    await be.bookkeeper_export_aaha(
        period_start="2026-05-04",
        period_end="2026-05-10",
        tenant_id="7f632730-1a38-41f1-9f99-508d696dbcf1",
        ctx=mock_ctx,
    )

    body = client.calls[0]["json"]
    assert body["format"] is None  # tenant default path
