"""Bookkeeper export endpoints — AAHA-categorized weekly delivery files.

Two entry points:
  - POST /generate                 — JWT-authenticated (UI / agent dashboards)
  - POST /internal/generate        — header-authenticated (MCP tool path)
  - GET  /download/{file_id}       — serves the previously-generated file

The actual format adapter lives in
`app.services.bookkeeper_exporters.*`. This router just plumbs the
HTTP layer in front of `app.services.bookkeeper_export.export_aaha`.

Files land in /tmp/agentprovision_bookkeeper with a 24-hour TTL so the
downstream Luna email + WhatsApp delivery have time to attach them.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models.user import User
from app.services.bookkeeper_export import export_aaha
from app.services.bookkeeper_exporters import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXPORTS_DIR = Path("/tmp/agentprovision_bookkeeper")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_TTL_HOURS = 24


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BookkeeperExportRequest(BaseModel):
    period_start: date
    period_end: date
    practice_name: str = "Practice"
    locations: list[str] = Field(default_factory=list)
    format: Optional[str] = None  # noqa: A003 — domain-specific name


class BookkeeperExportResponse(BaseModel):
    file_id: str
    filename: str
    download_url: str
    mime_type: str
    format: str  # noqa: A003
    line_item_count: int
    expires_at: str


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _cleanup_expired_exports() -> None:
    if not EXPORTS_DIR.exists():
        return
    cutoff = time.time() - (EXPORT_TTL_HOURS * 3600)
    for fpath in EXPORTS_DIR.iterdir():
        if fpath.is_file() and fpath.stat().st_mtime < cutoff:
            try:
                fpath.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Shared logic
# ---------------------------------------------------------------------------

_MIME_EXTENSIONS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "application/iif": ".iif",
}


def _do_export(
    db: Session,
    tenant_id: str,
    payload: BookkeeperExportRequest,
) -> dict:
    if payload.format and payload.format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported format '{payload.format}'. "
                f"Supported: {', '.join(SUPPORTED_FORMATS)}"
            ),
        )
    if payload.period_end < payload.period_start:
        raise HTTPException(
            status_code=400,
            detail="period_end must be >= period_start",
        )

    _cleanup_expired_exports()

    try:
        result = export_aaha(
            db=db,
            tenant_id=uuid.UUID(tenant_id),
            period_start=payload.period_start,
            period_end=payload.period_end,
            practice_name=payload.practice_name or "Practice",
            locations=tuple(payload.locations) if payload.locations else None,
            format=payload.format,
        )
    except FileNotFoundError as exc:
        # Taxonomy YAML missing — operational error, surface clearly
        logger.error("AAHA taxonomy YAML missing: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="AAHA taxonomy file is missing on the server.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    file_id = str(uuid.uuid4())
    ext = _MIME_EXTENSIONS.get(result.mime_type, "")
    if not ext:
        # Best-effort: derive from filename
        ext = Path(result.filename).suffix or ".bin"

    file_path = EXPORTS_DIR / f"{tenant_id}_{file_id}{ext}"
    file_path.write_bytes(result.content)
    logger.info(
        "Generated bookkeeper export %s (format=%s, items=?, tenant=%s)",
        file_id,
        payload.format or "tenant-default",
        tenant_id,
    )

    expires_at = (
        datetime.utcnow() + timedelta(hours=EXPORT_TTL_HOURS)
    ).isoformat()
    download_url = (
        f"/api/v1/bookkeeper-exports/download/{file_id}?tenant_id={tenant_id}"
    )

    # We don't have direct access to the count without re-running export
    # internals, but the adapter's filename includes period — so we
    # re-load the count cheaply by scanning the raw output isn't worth
    # it. Return a soft count (file size in bytes) instead so the MCP
    # tool surfaces something useful.
    return {
        "file_id": file_id,
        "filename": result.filename,
        "download_url": download_url,
        "mime_type": result.mime_type,
        "format": payload.format
        or _format_from_filename(result.filename),
        "line_item_count": -1,
        "expires_at": expires_at,
    }


def _format_from_filename(filename: str) -> str:
    fl = filename.lower()
    if fl.endswith(".xlsx"):
        return "xlsx"
    if fl.endswith(".iif"):
        return "quickbooks_iif"
    if "_qbo.csv" in fl:
        return "quickbooks_qbo"
    if "_xero.csv" in fl:
        return "xero_csv"
    if "_sage.csv" in fl:
        return "sage_intacct_csv"
    if fl.endswith(".csv"):
        return "csv"
    return "unknown"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=BookkeeperExportResponse)
def generate_export(
    payload: BookkeeperExportRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Generate an AAHA bookkeeper export — JWT-authenticated."""
    tenant_id = str(current_user.tenant_id)
    return _do_export(db, tenant_id, payload)


@router.post("/internal/generate", response_model=BookkeeperExportResponse)
def generate_export_internal(
    payload: BookkeeperExportRequest,
    db: Session = Depends(deps.get_db),
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_internal_key: str = Header(..., alias="X-Internal-Key"),
):
    """Generate an AAHA bookkeeper export — internal endpoint for MCP tool path.

    Mirrors the auth pattern used by `dynamic_workflows.verify_internal_key`
    — accepts either `API_INTERNAL_KEY` (in-cluster service-to-service)
    or `MCP_API_KEY` (MCP server).
    """
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")
    return _do_export(db, x_tenant_id, payload)


@router.get("/download/{file_id}")
def download_export(
    file_id: str,
    tenant_id: str = Query(...),
):
    """Serve a previously generated bookkeeper export for download."""
    if ".." in file_id or "/" in file_id or "\\" in file_id:
        raise HTTPException(status_code=400, detail="Invalid file_id")
    if ".." in tenant_id or "/" in tenant_id or "\\" in tenant_id:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    # Find the file regardless of extension — we don't know it from the URL
    matches = list(EXPORTS_DIR.glob(f"{tenant_id}_{file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Export not found or expired")
    file_path = matches[0]

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=file_path.name.split("_", 2)[-1] if "_" in file_path.name else file_path.name,
    )
