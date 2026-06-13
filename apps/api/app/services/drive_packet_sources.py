"""Tenant-scoped Drive packet metadata for vertical workspaces."""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.integration_config import IntegrationConfig
from app.services.orchestration.credential_vault import retrieve_credentials_for_skill

logger = logging.getLogger(__name__)

GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"


def _google_drive_token(
    db: Session,
    tenant_id: uuid.UUID,
    account_email: str | None = None,
    refresh: bool = False,
) -> tuple[str | None, str | None]:
    query = db.query(IntegrationConfig).filter(
        IntegrationConfig.tenant_id == tenant_id,
        IntegrationConfig.integration_name == "google_drive",
        IntegrationConfig.enabled.is_(True),
    )
    if account_email:
        query = query.filter(IntegrationConfig.account_email == account_email)
    config = query.order_by(IntegrationConfig.updated_at.desc()).first()
    if config is None:
        return None, None

    try:
        creds = retrieve_credentials_for_skill(db, config.id, tenant_id)
    except Exception:
        logger.exception("failed to load google_drive credential tenant=%s", tenant_id)
        return None, config.account_email

    refreshed_token = _refresh_google_drive_token(db, tenant_id, config, creds) if refresh else None
    return refreshed_token or creds.get("oauth_token"), config.account_email


def _refresh_google_drive_token(
    db: Session,
    tenant_id: uuid.UUID,
    config: IntegrationConfig,
    creds: dict[str, str],
) -> str | None:
    """Refresh the Drive access token when a Google refresh token is available."""
    refresh_token = creds.get("refresh_token")
    if not refresh_token and config.account_email:
        siblings = (
            db.query(IntegrationConfig)
            .filter(
                IntegrationConfig.tenant_id == tenant_id,
                IntegrationConfig.account_email == config.account_email,
                IntegrationConfig.enabled.is_(True),
                IntegrationConfig.id != config.id,
            )
            .all()
        )
        for sibling in siblings:
            sibling_creds = retrieve_credentials_for_skill(db, sibling.id, tenant_id)
            refresh_token = sibling_creds.get("refresh_token")
            if refresh_token:
                break

    if not refresh_token:
        return None

    try:
        from app.api.v1.oauth import _refresh_access_token, _update_stored_tokens

        refreshed = _refresh_access_token("google", refresh_token, integration_name="google_drive")
        if not refreshed:
            return None
        _update_stored_tokens(
            db,
            config.id,
            tenant_id,
            refreshed["access_token"],
            refreshed.get("refresh_token"),
        )
        return refreshed["access_token"]
    except Exception:
        logger.exception("failed to refresh google_drive token tenant=%s config=%s", tenant_id, config.id)
        return None


def _file_kind(mime_type: str | None) -> str:
    if mime_type == GOOGLE_FOLDER_MIME:
        return "folder"
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type and mime_type.startswith("application/vnd.google-apps."):
        return "google_doc"
    return "file"


def list_google_drive_packet(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    folder_id: str,
    label: str = "Drive packet",
    account_email: str | None = None,
    max_children: int = 25,
) -> dict[str, Any]:
    """Return safe Drive folder/file metadata for a configured packet root.

    This intentionally does not read file contents. Workflows call the MCP
    Drive read tool when extraction is needed; the workspace only needs enough
    metadata to show operators that the source packet is present and usable.
    """
    if not folder_id:
        return {
            "label": label,
            "provider": "google_drive",
            "state": "setup_required",
            "error": "missing_folder_id",
            "files": [],
        }

    token, connected_email = _google_drive_token(db, tenant_id, account_email)
    if not token:
        return {
            "label": label,
            "provider": "google_drive",
            "folder_id": folder_id,
            "account_email": connected_email or account_email,
            "state": "setup_required",
            "error": "google_drive_not_connected",
            "files": [],
        }

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=15.0) as client:
            folder_resp = None
            for attempt in range(2):
                folder_resp = client.get(
                    f"https://www.googleapis.com/drive/v3/files/{folder_id}",
                    headers=headers,
                    params={
                        "fields": "id,name,mimeType,modifiedTime,webViewLink,parents",
                        "supportsAllDrives": "true",
                    },
                )
                if folder_resp.status_code != 401 or attempt == 1:
                    break
                refreshed_token, connected_email = _google_drive_token(
                    db,
                    tenant_id,
                    account_email,
                    refresh=True,
                )
                if not refreshed_token or refreshed_token == token:
                    break
                token = refreshed_token
                headers = {"Authorization": f"Bearer {token}"}
            if folder_resp.status_code == 401:
                return {
                    "label": label,
                    "provider": "google_drive",
                    "folder_id": folder_id,
                    "account_email": connected_email or account_email,
                    "state": "setup_required",
                    "error": "token_expired",
                    "files": [],
                }
            if folder_resp.status_code != 200:
                return {
                    "label": label,
                    "provider": "google_drive",
                    "folder_id": folder_id,
                    "account_email": connected_email or account_email,
                    "state": "error",
                    "error": f"folder_lookup_failed:{folder_resp.status_code}",
                    "files": [],
                }

            folder = folder_resp.json()
            files_resp = client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params={
                    "q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink)",
                    "orderBy": "name",
                    "pageSize": max(1, min(max_children, 100)),
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
            )
            if files_resp.status_code != 200:
                return {
                    "label": label,
                    "provider": "google_drive",
                    "folder_id": folder_id,
                    "folder_name": folder.get("name"),
                    "account_email": connected_email or account_email,
                    "state": "error",
                    "error": f"children_lookup_failed:{files_resp.status_code}",
                    "files": [],
                }
            raw_files = files_resp.json().get("files", [])
    except httpx.HTTPError:
        logger.exception("google drive packet lookup failed tenant=%s folder=%s", tenant_id, folder_id)
        return {
            "label": label,
            "provider": "google_drive",
            "folder_id": folder_id,
            "account_email": connected_email or account_email,
            "state": "error",
            "error": "drive_request_failed",
            "files": [],
        }

    files = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "kind": _file_kind(item.get("mimeType")),
            "mime_type": item.get("mimeType"),
            "size": item.get("size"),
            "modified": item.get("modifiedTime"),
            "link": item.get("webViewLink"),
        }
        for item in raw_files
    ]
    pdf_count = sum(1 for item in files if item["kind"] == "pdf")
    return {
        "label": label,
        "provider": "google_drive",
        "folder_id": folder_id,
        "folder_name": folder.get("name"),
        "folder_link": folder.get("webViewLink"),
        "account_email": connected_email or account_email,
        "state": "ready" if files else "empty",
        "error": None,
        "counts": {
            "files": len(files),
            "pdfs": pdf_count,
            "folders": sum(1 for item in files if item["kind"] == "folder"),
        },
        "files": files,
    }
