"""Bookkeeper export endpoints — AAHA-categorized weekly delivery files.

Two entry points:
  - POST /generate                 — JWT-authenticated (UI / agent dashboards)
  - POST /internal/generate        — header-authenticated (MCP tool path)
  - GET  /download/{file_id}       — HMAC-signed URL (no headers needed)

The actual format adapter lives in
`app.services.bookkeeper_exporters.*`. This router just plumbs the
HTTP layer in front of `app.services.bookkeeper_export.export_aaha`.

Files land in /tmp/agentprovision_bookkeeper with a 24-hour TTL so the
downstream Luna email + WhatsApp delivery have time to attach them.

SECURITY (PR #331 review Critical #1): the download path was originally
unauthenticated — anyone who learned a (file_id, tenant_id) pair could
fetch a tenant's full week of categorized financial line items. Now
every download URL is HMAC-signed (sig + expiry encoded as query
params). The signature is computed over file_id + tenant_id + expiry
with `settings.SECRET_KEY` as the key; the verifier uses
`hmac.compare_digest`. Email + WhatsApp recipients open the link
directly; no auth headers required, but anyone without the signed URL
gets 403.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
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


# ---------------------------------------------------------------------------
# HMAC-signed download URLs (PR #331 Critical #1 fix)
# ---------------------------------------------------------------------------

_DOWNLOAD_SIG_TTL_SECONDS = EXPORT_TTL_HOURS_PLACEHOLDER = 24 * 3600  # matches EXPORTS_DIR TTL


def _sign_download(file_id: str, tenant_id: str, expires_at: int) -> str:
    """HMAC-SHA256 signature for download URLs.

    Signed payload: ``f"{file_id}|{tenant_id}|{expires_at}"``. Truncated
    to 128 bits + URL-safe base64 (32 chars without padding) — same
    strength as a UUID4, no signature-collision risk in practice.
    """
    secret = settings.SECRET_KEY.encode("utf-8")
    payload = f"{file_id}|{tenant_id}|{expires_at}".encode("utf-8")
    digest = _hmac.new(secret, payload, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _verify_download(
    file_id: str, tenant_id: str, expires_at: int, sig: str
) -> bool:
    """Constant-time verify — returns False on any mismatch or expiry."""
    if expires_at < int(time.time()):
        return False
    expected = _sign_download(file_id, tenant_id, expires_at)
    return _hmac.compare_digest(expected, sig)

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

    expires_ts = int(time.time()) + EXPORT_TTL_HOURS * 3600
    expires_at = datetime.utcfromtimestamp(expires_ts).isoformat()
    sig = _sign_download(file_id, tenant_id, expires_ts)
    download_url = (
        f"/api/v1/bookkeeper-exports/download/{file_id}"
        f"?tenant_id={tenant_id}&expires={expires_ts}&sig={sig}"
    )

    # Resolved format: adapter returns it explicitly now (review feedback
    # PR #331 Minor #6). Fall back to filename-sniff only if the adapter
    # didn't populate the field (legacy callers); never return 'unknown'
    # back to the user when we can derive it.
    resolved_format = (
        payload.format
        or getattr(result, "format", "")
        or _format_from_filename(result.filename)
    )
    return {
        "file_id": file_id,
        "filename": result.filename,
        "download_url": download_url,
        "mime_type": result.mime_type,
        "format": resolved_format,
        "line_item_count": getattr(result, "line_item_count", 0),
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
    expires: int = Query(..., description="Unix-seconds expiry from the signed URL"),
    sig: str = Query(..., description="HMAC-SHA256 signature; URL-safe base64"),
):
    """Serve a previously generated bookkeeper export for download.

    SECURITY (PR #331 Critical #1): the URL must be HMAC-signed by
    /generate. Without a valid signature this returns 403 — enforces
    tenant isolation since the signature is bound to (file_id, tenant_id,
    expiry) and computed with the platform's SECRET_KEY. Path-traversal
    sanitization is kept as defense-in-depth.
    """
    if ".." in file_id or "/" in file_id or "\\" in file_id:
        raise HTTPException(status_code=400, detail="Invalid file_id")
    if ".." in tenant_id or "/" in tenant_id or "\\" in tenant_id:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    # Reject unsigned / expired / forged URLs before any filesystem touch.
    if not _verify_download(file_id, tenant_id, expires, sig):
        # Don't disclose whether the file exists or only the signature failed.
        raise HTTPException(status_code=403, detail="Invalid or expired download link")

    matches = list(EXPORTS_DIR.glob(f"{tenant_id}_{file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Export not found or expired")
    file_path = matches[0]

    return FileResponse(
        path=str(file_path),
        media_type="application/octet-stream",
        filename=file_path.name.split("_", 2)[-1] if "_" in file_path.name else file_path.name,
    )
