"""OneDrive MCP tools.

Minimal Microsoft Graph file creation for MVP file-packet workflows.
"""
import logging
import os
from typing import Optional
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_INTERNAL_KEY = os.environ.get("MCP_API_KEY", "dev_mcp_key")


async def _get_onedrive_token(
    tenant_id: str,
    account_email: str = "",
) -> Optional[str]:
    params = {"tenant_id": tenant_id}
    if account_email:
        params["account_email"] = account_email
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{API_BASE_URL}/api/v1/oauth/internal/token/onedrive",
            headers={"X-Internal-Key": API_INTERNAL_KEY},
            params=params,
        )
        if resp.status_code == 200:
            return resp.json().get("oauth_token")
    return None


@mcp.tool()
async def create_onedrive_file(
    name: str,
    content: str,
    mime_type: str = "text/plain",
    folder_id: str = "",
    tenant_id: str = "",
    account_email: str = "",
    ctx: Context = None,
) -> dict:
    """Create a text file in the signed-in user's OneDrive.

    Args:
        name: File name, e.g. ``report.md``.
        content: File content as text.
        mime_type: MIME type for the uploaded content.
        folder_id: Optional OneDrive folder item ID. Empty writes to root.
        tenant_id: Tenant UUID.
        account_email: Specific Microsoft account.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    token = await _get_onedrive_token(tid, account_email)
    if not token:
        return {"error": "OneDrive not connected."}

    encoded_name = quote(name, safe="")
    if folder_id:
        url = (
            "https://graph.microsoft.com/v1.0/me/drive/items/"
            f"{folder_id}:/{encoded_name}:/content"
        )
    else:
        url = (
            "https://graph.microsoft.com/v1.0/me/drive/root:/"
            f"{encoded_name}:/content"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": mime_type,
            },
            content=content.encode("utf-8"),
        )

    if resp.status_code in {200, 201}:
        payload = resp.json()
        return {
            "status": "success",
            "id": payload.get("id"),
            "name": payload.get("name", name),
            "web_url": payload.get("webUrl"),
        }
    if resp.status_code == 401:
        return {"error": "OneDrive token expired. Reconnect Microsoft in Integrations."}
    if resp.status_code == 403:
        return {"error": "OneDrive token lacks file-write permission. Reconnect Microsoft."}
    return {
        "error": (
            f"Failed to create OneDrive file: {resp.status_code} "
            f"{resp.text[:200]}"
        )
    }
