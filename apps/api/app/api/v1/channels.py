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


# ── Teams Channel ────────────────────────────────────────────────────
# Microsoft Teams via Bot Framework. Per-tenant BYO Azure Bot —
# customer creates the Bot in their Azure subscription, gives us App ID
# + secret, points the bot's messaging endpoint at our webhook.

from fastapi import Request
from app.services.teams_service import teams_service


class TeamsEnableRequest(BaseModel):
    microsoft_app_id: str
    microsoft_app_secret: str
    azure_tenant_id: str | None = None
    bot_handle: str | None = None
    dm_policy: str = "allowlist"
    allow_from: List[str] = []
    account_id: str = "default"


class TeamsSettingsRequest(BaseModel):
    dm_policy: str = "allowlist"
    allow_from: List[str] = []
    account_id: str = "default"


class TeamsAccountIdRequest(BaseModel):
    account_id: str = "default"


class TeamsSendRequest(BaseModel):
    text: str
    conversation_reference: dict
    account_id: str = "default"


@router.post("/teams/enable")
async def enable_teams(
    request: TeamsEnableRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Enable Teams channel for this tenant. Returns the webhook URL the
    customer must paste into their Azure Bot's `Messaging endpoint` field.
    """
    try:
        result = await teams_service.enable(
            str(current_user.tenant_id),
            request.account_id,
            microsoft_app_id=request.microsoft_app_id,
            microsoft_app_secret=request.microsoft_app_secret,
            azure_tenant_id=request.azure_tenant_id,
            bot_handle=request.bot_handle,
            dm_policy=request.dm_policy,
            allow_from=request.allow_from,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    result = await teams_service.get_status(str(current_user.tenant_id), account_id)
    return result


@router.post("/teams/send")
async def send_teams(
    request: TeamsSendRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Send a Teams message. Caller must supply the conversation_reference
    captured from a prior inbound activity (or persisted from one).
    """
    result = await teams_service.send_message(
        str(current_user.tenant_id),
        request.text,
        account_id=request.account_id,
        conversation_reference=request.conversation_reference,
    )
    if not result.get("sent"):
        raise HTTPException(status_code=502, detail=result)
    return {"status": "sent", "data": result}


@router.post("/teams/webhook/{tenant_id}/{account_id}/{webhook_secret}")
async def teams_webhook(
    tenant_id: str,
    account_id: str,
    webhook_secret: str,
    request: Request,
):
    """Bot Framework webhook for inbound Teams activities.

    PUBLIC endpoint — auth is by URL secret (tenant-scoped, unguessable)
    PLUS Bot Framework JWT signature validation inside the service.
    """
    auth_header = request.headers.get("authorization", "")
    try:
        activity = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    result = await teams_service.handle_inbound(
        tenant_id=tenant_id,
        account_id=account_id,
        webhook_path_secret=webhook_secret,
        authorization_header=auth_header,
        activity=activity,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=401 if "jwt" in str(result.get("reason", "")).lower() else 400,
            detail=result.get("reason", "rejected"),
        )
    return result
