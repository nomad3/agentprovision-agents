"""Luna Presence API — real-time state, mood, and shell tracking."""
import hashlib
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.device_registry import DeviceRegistry
from app.schemas.luna_presence import LunaPresenceUpdate, ShellRegisterRequest, ShellDeregisterRequest
from app.services import luna_presence_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/presence", tags=["presence"])


@router.get("")
def get_presence(current_user=Depends(get_current_user)):
    return luna_presence_service.get_presence(current_user.tenant_id)


@router.put("")
def update_presence(body: LunaPresenceUpdate, current_user=Depends(get_current_user)):
    return luna_presence_service.update_state(
        current_user.tenant_id,
        state=body.state, mood=body.mood, privacy=body.privacy,
        active_shell=body.active_shell, tool_status=body.tool_status,
        attention_target=body.attention_target, session_id=body.session_id,
    )


@router.post("/shell/register")
def register_shell(
    body: ShellRegisterRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    x_device_token: str | None = Header(None, alias="X-Device-Token"),
):
    device_registry_id = None
    if body.device_id:
        if not x_device_token:
            raise HTTPException(status_code=401, detail="X-Device-Token required")
        token_hash = hashlib.sha256(x_device_token.encode()).hexdigest()
        device = db.query(DeviceRegistry).filter(
            DeviceRegistry.tenant_id == current_user.tenant_id,
            DeviceRegistry.device_id == body.device_id,
            DeviceRegistry.device_type == "desktop",
            DeviceRegistry.device_token_hash == token_hash,
        ).first()
        if not device:
            raise HTTPException(status_code=401, detail="Invalid desktop device token")
        if (device.config or {}).get("shell_id") != body.shell:
            raise HTTPException(status_code=403, detail="Device is not bound to shell")
        device.status = "online"
        device.last_heartbeat = datetime.utcnow()
        device.updated_at = datetime.utcnow()
        db.commit()
        device_registry_id = str(device.id)

    return luna_presence_service.register_shell(
        current_user.tenant_id,
        body.shell,
        capabilities=body.capabilities,
        device_registry_id=device_registry_id,
        device_id=body.device_id,
        permission_readiness=body.permission_readiness,
    )


@router.post("/shell/deregister")
def deregister_shell(body: ShellDeregisterRequest, current_user=Depends(get_current_user)):
    return luna_presence_service.deregister_shell(current_user.tenant_id, body.shell)
