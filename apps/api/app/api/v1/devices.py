"""Device registry and robot interaction API."""
import hashlib
import logging
import re
import secrets
from datetime import datetime
from typing import Dict, List, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_db
from app.models.device_registry import DeviceRegistry
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["devices"])

_DESKTOP_SHELL_ID_RE = re.compile(
    r"^desktop-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def get_device_by_token(
    x_device_token: str = Header(..., alias="X-Device-Token"),
    db: Session = Depends(get_db),
) -> DeviceRegistry:
    """Authenticate a device by its token. Used for heartbeat and device-originated requests."""
    token_hash = hashlib.sha256(x_device_token.encode()).hexdigest()
    device = db.query(DeviceRegistry).filter(
        DeviceRegistry.device_token_hash == token_hash,
    ).first()
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device token")
    return device


class DeviceRegisterRequest(BaseModel):
    device_name: str
    device_type: Literal["camera", "robot", "necklace", "glasses", "sensor"]
    capabilities: List[str] = []
    config: dict = {}


class DesktopDeviceEnrollRequest(BaseModel):
    shell_id: str = Field(..., max_length=96)
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    app_version: str | None = Field(default=None, max_length=64)


def _desktop_device_id(tenant_id, shell_id: str) -> str:
    return f"{tenant_id}-desktop-{shell_id.removeprefix('desktop-')}"


@router.get("")
def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    devices = db.query(DeviceRegistry).filter(
        DeviceRegistry.tenant_id == current_user.tenant_id,
    ).order_by(DeviceRegistry.created_at.desc()).all()
    return [
        {
            "id": str(d.id),
            "device_id": d.device_id,
            "device_name": d.device_name,
            "device_type": d.device_type,
            "status": d.status,
            "capabilities": d.capabilities or [],
            "last_heartbeat": d.last_heartbeat.isoformat() if d.last_heartbeat else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in devices
    ]


@router.post("")
def register_device(
    body: DeviceRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    device_id = f"{current_user.tenant_id}-{body.device_type}-{secrets.token_hex(4)}"

    device = DeviceRegistry(
        tenant_id=current_user.tenant_id,
        device_id=device_id,
        device_name=body.device_name,
        device_type=body.device_type,
        status="offline",
        device_token_hash=token_hash,
        capabilities=body.capabilities,
        config=body.config,
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    return {
        "id": str(device.id),
        "device_id": device.device_id,
        "device_token": token,  # Only returned once!
        "message": "Save this token — it won't be shown again.",
    }


@router.post("/desktop/enroll")
def enroll_desktop_device(
    body: DesktopDeviceEnrollRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not _DESKTOP_SHELL_ID_RE.fullmatch(body.shell_id):
        raise HTTPException(status_code=422, detail="shell_id must be a desktop UUID shell")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    device_id = _desktop_device_id(current_user.tenant_id, body.shell_id)
    enabled_capabilities = sorted(
        key for key, enabled in body.capabilities.items()
        if key.startswith("can_") and enabled is True
    )

    device = db.query(DeviceRegistry).filter(
        DeviceRegistry.tenant_id == current_user.tenant_id,
        DeviceRegistry.device_id == device_id,
    ).first()
    if device is None:
        device = DeviceRegistry(
            tenant_id=current_user.tenant_id,
            device_id=device_id,
            device_name="Luna Desktop",
            device_type="desktop",
            status="online",
        )
        db.add(device)

    device.device_name = "Luna Desktop"
    device.device_type = "desktop"
    device.status = "online"
    device.device_token_hash = token_hash
    device.last_heartbeat = datetime.utcnow()
    device.capabilities = enabled_capabilities
    device.config = {
        **(device.config or {}),
        "shell_id": body.shell_id,
        "capability_manifest": body.capabilities,
        "app_version": body.app_version,
        "enrolled_by_user_id": str(current_user.id),
    }
    device.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(device)

    return {
        "id": str(device.id),
        "device_id": device.device_id,
        "device_token": token,
        "shell_id": body.shell_id,
    }


@router.delete("/{device_id}")
def remove_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    device = db.query(DeviceRegistry).filter(
        DeviceRegistry.device_id == device_id,
        DeviceRegistry.tenant_id == current_user.tenant_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    db.delete(device)
    db.commit()
    return {"status": "removed", "device_id": device_id}


@router.post("/{device_id}/heartbeat")
def device_heartbeat(
    device_id: str,
    db: Session = Depends(get_db),
    device: DeviceRegistry = Depends(get_device_by_token),
):
    if device.device_id != device_id:
        raise HTTPException(status_code=403, detail="Token does not match device")
    device.status = "online"
    device.last_heartbeat = datetime.utcnow()
    db.commit()
    return {"status": "ok", "device_id": device_id}
