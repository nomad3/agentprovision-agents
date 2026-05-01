"""WhatsApp channel management endpoints using neonize (direct integration)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List

from app.api import deps
from app.models.user import User
from app.services.whatsapp_service import whatsapp_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request Models ───────────────────────────────────────────────────

class WhatsAppEnableRequest(BaseModel):
    dm_policy: str = "allowlist"
    allow_from: List[str] = []
    account_id: str = "default"


class WhatsAppSendRequest(BaseModel):
    to: str
    message: str
    account_id: str = "default"


class WhatsAppPairRequest(BaseModel):
    force: bool = False
    account_id: str = "default"


class WhatsAppLogoutRequest(BaseModel):
    account_id: str = "default"


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/whatsapp/enable")
async def enable_whatsapp(
    request: WhatsAppEnableRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Enable the WhatsApp channel for this tenant."""
    allow_from = request.allow_from
    if request.dm_policy == "open" and "*" not in allow_from:
        allow_from = ["*"] + allow_from
    result = await whatsapp_service.enable(
        str(current_user.tenant_id), request.account_id,
        request.dm_policy, allow_from,
    )
    return {"status": "enabled", "data": result}


@router.post("/whatsapp/disable")
async def disable_whatsapp(
    request: WhatsAppLogoutRequest = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Disable the WhatsApp channel."""
    account_id = request.account_id if request else "default"
    result = await whatsapp_service.disable(
        str(current_user.tenant_id), account_id,
    )
    return {"status": "disabled", "data": result}


@router.put("/whatsapp/settings")
async def update_whatsapp_settings(
    request: WhatsAppEnableRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Update WhatsApp channel settings (allowlist, DM policy) without re-enabling."""
    allow_from = request.allow_from
    if request.dm_policy == "open" and "*" not in allow_from:
        allow_from = ["*"] + allow_from
    result = await whatsapp_service.update_settings(
        str(current_user.tenant_id), request.account_id,
        request.dm_policy, allow_from,
    )
    return {"status": "updated", "data": result}


@router.get("/whatsapp/status")
async def whatsapp_status(
    account_id: str = Query("default"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Get WhatsApp channel connection status."""
    result = await whatsapp_service.get_status(
        str(current_user.tenant_id), account_id,
    )
    return result


@router.post("/whatsapp/pair")
async def start_pairing(
    request: WhatsAppPairRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Start WhatsApp QR pairing. Returns a QR data URL for scanning."""
    result = await whatsapp_service.start_pairing(
        str(current_user.tenant_id), request.account_id, request.force,
    )
    if not result.get("qr_data_url") and not result.get("connected"):
        raise HTTPException(status_code=504, detail=result.get("message", "QR generation timed out"))
    return {
        "qr_data_url": result.get("qr_data_url"),
        "message": result.get("message", "Scan the QR code with WhatsApp"),
        "connected": result.get("connected", False),
    }


@router.get("/whatsapp/pair/status")
async def pairing_status(
    account_id: str = Query("default"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Poll for pairing completion."""
    result = await whatsapp_service.get_pairing_status(
        str(current_user.tenant_id), account_id,
    )
    return {
        "connected": result.get("connected", False),
        "status": result.get("status", "disconnected"),
        "message": "Connected" if result.get("connected") else "Waiting for QR scan",
    }


@router.post("/whatsapp/logout")
async def logout_whatsapp(
    request: WhatsAppLogoutRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Logout/unlink WhatsApp account."""
    result = await whatsapp_service.logout(
        str(current_user.tenant_id), request.account_id,
    )
    return {"status": "logged_out", "data": result}


@router.post("/whatsapp/send")
async def send_whatsapp(
    request: WhatsAppSendRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Send a WhatsApp message."""
    result = await whatsapp_service.send_message(
        str(current_user.tenant_id), request.account_id,
        request.to, request.message,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("error", "Send failed"))
    return {"status": "sent", "data": result}


# ── Teams Channel (Microsoft Graph via existing microsoft OAuth) ──
# Reuses the same app registration / OAuth tokens as Outlook.
# Pre-condition: tenant has authorized the `microsoft` provider via the
# Outlook integration card (or any future microsoft-provider card).
# This endpoint group flips the Teams channel on/off and exposes
# basic management; inbound polling is handled by the Teams Monitor
# workflow (analogous to Inbox Monitor).

from app.services.teams_service import teams_service


class TeamsEnableRequest(BaseModel):
    dm_policy: str = "allowlist"
    allow_from: List[str] = []
    account_id: str = "default"


class TeamsSettingsRequest(BaseModel):
    dm_policy: str = "allowlist"
    allow_from: List[str] = []
    account_id: str = "default"


class TeamsAccountIdRequest(BaseModel):
    account_id: str = "default"


class TeamsSendChatRequest(BaseModel):
    chat_id: str
    text: str
    account_id: str = "default"


class TeamsSendChannelRequest(BaseModel):
    team_id: str
    channel_id: str
    text: str
    account_id: str = "default"


@router.post("/teams/enable")
async def enable_teams(
    request: TeamsEnableRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Enable Teams channel for this tenant.

    Pre-condition: the tenant has already authorized the `microsoft` OAuth
    provider (via the Outlook integration card or similar). The Graph
    access_token is reused for Teams API calls.
    """
    result = await teams_service.enable(
        str(current_user.tenant_id),
        request.account_id,
        dm_policy=request.dm_policy,
        allow_from=request.allow_from,
    )
    if not result.get("enabled"):
        raise HTTPException(status_code=400, detail=result.get("reason", "enable failed"))
    return {"status": "enabled", "data": result}


@router.post("/teams/disable")
async def disable_teams(
    request: TeamsAccountIdRequest = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    account_id = request.account_id if request else "default"
    result = await teams_service.disable(str(current_user.tenant_id), account_id)
    return {"status": "disabled", "data": result}


@router.put("/teams/settings")
async def update_teams_settings(
    request: TeamsSettingsRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    result = await teams_service.update_settings(
        str(current_user.tenant_id),
        request.account_id,
        request.dm_policy,
        request.allow_from,
    )
    return {"status": "updated", "data": result}


@router.get("/teams/status")
async def teams_status(
    account_id: str = Query("default"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    return await teams_service.get_status(str(current_user.tenant_id), account_id)


@router.get("/teams/chats")
async def list_teams_chats(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """List the user's Teams chats (1:1 + group). Uses the Graph token."""
    chats = await teams_service.list_chats(str(current_user.tenant_id))
    return {"chats": chats}


@router.post("/teams/send/chat")
async def send_teams_chat(
    request: TeamsSendChatRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Send a message to a Teams chat (1:1 or group)."""
    result = await teams_service.send_chat_message(
        str(current_user.tenant_id), request.chat_id, request.text,
    )
    if not result.get("sent"):
        raise HTTPException(status_code=502, detail=result)
    return {"status": "sent", "data": result}


@router.post("/teams/send/channel")
async def send_teams_channel(
    request: TeamsSendChannelRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Send a message to a Team channel."""
    result = await teams_service.send_channel_message(
        str(current_user.tenant_id),
        request.team_id,
        request.channel_id,
        request.text,
    )
    if not result.get("sent"):
        raise HTTPException(status_code=502, detail=result)
    return {"status": "sent", "data": result}


@router.post("/teams/poll")
async def poll_teams(
    request: TeamsAccountIdRequest = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Manual trigger of a Teams Monitor tick (for testing).

    Production deployments rely on the Teams Monitor workflow firing
    every N minutes via continue_as_new — analogous to Inbox Monitor.
    """
    account_id = request.account_id if request else "default"
    result = await teams_service.monitor_tick(
        str(current_user.tenant_id), account_id,
    )
    return result
