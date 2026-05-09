"""Bookkeeper export MCP tool.

Single tool, `bookkeeper_export_aaha`, that the Bookkeeper Categorization
workflow's final delivery step calls to produce the weekly file. Looks
up `tenant_features.cpa_export_format` if the caller doesn't pass an
explicit format, dispatches to the matching adapter on the API side,
and returns the download URL + file metadata.

The actual format adapter logic lives on the API side at
`apps/api/app/services/bookkeeper_exporters/*`. This MCP tool is a
thin pass-through that lets the workflow step + chat agents trigger an
export without holding a DB connection.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


SUPPORTED_FORMATS = (
    "xlsx",
    "csv",
    "quickbooks_iif",
    "quickbooks_qbo",
    "xero_csv",
    "sage_intacct_csv",
)


def _get_api_base_url() -> str:
    from src.config import settings
    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings
    return settings.API_INTERNAL_KEY


@mcp.tool()
async def bookkeeper_export_aaha(
    period_start: str,
    period_end: str,
    practice_name: str = "Practice",
    locations: Optional[list[str]] = None,
    format: Optional[str] = None,            # noqa: A002 — domain-specific name
    tenant_id: str = "",
    ctx: Context = None,
) -> dict:
    """Generate the AAHA-categorized bookkeeper export for a tenant.

    AAHA is the canonical taxonomy. This tool runs the AAHA-categorized
    rows through the format adapter the tenant's CPA expects (XLSX,
    generic CSV, QuickBooks IIF, QuickBooks Online CSV, Xero CSV, or
    Sage Intacct CSV). Format priority:
       1. Explicit `format` arg (when provided)
       2. `tenant_features.cpa_export_format` for the tenant
       3. xlsx (default)

    Args:
        period_start: ISO date (YYYY-MM-DD) — inclusive lower bound.
        period_end:   ISO date (YYYY-MM-DD) — inclusive upper bound.
        practice_name: Display name used in filenames + cover sheet.
        locations: Optional list of location labels for multi-clinic
                   tenants. When omitted, locations are auto-derived
                   from the line items themselves.
        format: One of: xlsx | csv | quickbooks_iif | quickbooks_qbo
                | xero_csv | sage_intacct_csv. Omit to use the tenant
                default.
        tenant_id: Tenant UUID (resolved from MCP session if omitted).

    Returns:
        Dict with status, download_url, filename, file_id, format,
        mime_type, expires_at.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}
    if not period_start or not period_end:
        return {"error": "period_start and period_end are required (YYYY-MM-DD)."}
    if format and format not in SUPPORTED_FORMATS:
        return {
            "error": (
                f"Unsupported format '{format}'. "
                f"Supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        }

    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "practice_name": practice_name or "Practice",
        "locations": locations or [],
        "format": format,
    }

    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{api_base_url}/api/v1/bookkeeper-exports/internal/generate",
                headers={
                    "X-Tenant-Id": tid,
                    "X-Internal-Key": internal_key,
                },
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            return {
                "status": "success",
                "file_id": result.get("file_id"),
                "filename": result.get("filename"),
                "download_url": result.get("download_url"),
                "format": result.get("format"),
                "mime_type": result.get("mime_type"),
                "expires_at": result.get("expires_at"),
                "message": (
                    f"AAHA bookkeeper export ready as {result.get('format')}. "
                    f"Download: {result.get('download_url')}"
                ),
            }
    except httpx.HTTPStatusError as exc:
        logger.error(
            "bookkeeper_export_aaha HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:300],
        )
        return {
            "error": f"API returned {exc.response.status_code}: "
                     f"{exc.response.text[:200]}"
        }
    except Exception as exc:
        logger.exception("bookkeeper_export_aaha failed")
        return {"error": f"Failed to generate bookkeeper export: {exc}"}
