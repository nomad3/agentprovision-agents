"""MCP tools for device management."""
import logging
import json
import os
from typing import Optional

from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


@mcp.tool()
async def list_connected_devices(tenant_id: str = "", ctx: Context = None) -> dict:
    """List all registered devices for the tenant."""
    from src.mcp_tools.knowledge import _get_pool

    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required"}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT device_id, device_name, device_type, status, last_heartbeat "
            "FROM device_registry WHERE tenant_id = $1 "
            "ORDER BY last_heartbeat DESC NULLS LAST",
            tid,
        )
    return {"devices": [dict(r) for r in rows], "count": len(rows)}


@mcp.tool()
async def get_device_status(device_id: str, tenant_id: str = "", ctx: Context = None) -> dict:
    """Get status of a specific device."""
    from src.mcp_tools.knowledge import _get_pool

    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required"}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT device_id, device_name, device_type, status, capabilities, last_heartbeat, created_at FROM device_registry WHERE device_id = $1 AND tenant_id = $2",
            device_id, tid,
        )
    if not row:
        return {"error": "Device not found"}
    return dict(row)


@mcp.tool()
async def get_device_config(device_id: str, tenant_id: str = "", ctx: Context = None) -> dict:
    """Get the full configuration of a device including local RTSP/bridge settings."""
    from src.mcp_tools.knowledge import _get_pool

    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required"}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT device_id, config FROM device_registry WHERE device_id = $1 AND tenant_id = $2",
            device_id, tid,
        )
    if not row:
        return {"error": "Device not found"}
    return {"device_id": device_id, "config": json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]}


@mcp.tool()
async def capture_camera_snapshot(device_id: str, tenant_id: str = "", ctx: Context = None) -> dict:
    """Capture a live frame from a camera via the device bridge and upload to Luna vision."""
    from src.mcp_tools.knowledge import _get_pool
    import httpx

    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id required"}

    # 1. Get bridge URL from device config
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT device_id, config, device_token_hash FROM device_registry WHERE device_id = $1 AND tenant_id = $2",
            device_id, tid,
        )
    if not row:
        return {"error": "Camera not found"}
    
    config = json.loads(row["config"]) if isinstance(row["config"], str) else (row["config"] or {})
    bridge_url = config.get("bridge_url", "http://localhost:8088")

    # 2. Request snapshot from bridge
    try:
        async with httpx.AsyncClient() as client:
            # The bridge should have a /snapshot endpoint that returns base64
            resp = await client.post(f"{bridge_url}/cameras/{device_id}/snapshot", timeout=10.0)
            if resp.status_code != 200:
                return {"error": f"Bridge returned error: {resp.text}"}
            
            snapshot_data = resp.json()
            image_b64 = snapshot_data.get("image_b64")
            
            # 3. Upload to Luna Vision API
            # This makes the image available for the next LLM turn
            api_url = os.getenv("API_BASE_URL", "http://api:8000/api/v1")
            # We'd need the raw device token here to auth as the device, 
            # or use an internal key. For this tool, we'll assume the internal key.
            internal_key = os.getenv("API_INTERNAL_KEY")
            
            vision_resp = await client.post(
                f"{api_url}/robot/vision/snapshot",
                json={
                    "image_b64": image_b64,
                    "source": device_id,
                    "context": f"Captured via capture_camera_snapshot tool by agent."
                },
                headers={"X-Internal-Key": internal_key}
            )
            
            if vision_resp.status_code == 200:
                return {
                    "status": "success", 
                    "message": "Snapshot captured and ingested into Luna's vision system.",
                    "timestamp": snapshot_data.get("timestamp")
                }
            else:
                return {"error": f"Failed to upload to vision API: {vision_resp.text}"}

    except Exception as e:
        logger.exception("Snapshot capture failed")
        return {"error": f"Snapshot failed: {str(e)}"}
