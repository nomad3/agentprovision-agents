from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import uuid

from app.api import deps
from app.models.user import User
from app.services.orchestration.skill_router import SkillRouter

router = APIRouter()


class SkillExecuteRequest(BaseModel):
    skill_name: str
    payload: dict
    task_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None


@router.post("/execute")
def execute_skill(
    request: SkillExecuteRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Execute a skill through the tenant's OpenClaw instance."""
    import logging
    logger = logging.getLogger(__name__)
    skill_router = SkillRouter(db=db, tenant_id=current_user.tenant_id)
    result = skill_router.execute_skill(
        skill_name=request.skill_name,
        payload=request.payload,
        task_id=request.task_id,
        agent_id=request.agent_id,
    )
    if result.get("status") == "error":
        error_detail = result.get("error", "Unknown error")
        logger.error("Skill execution failed for '%s': %s", request.skill_name, error_detail)
        raise HTTPException(status_code=502, detail=error_detail)
    return result


@router.get("/health")
def skill_health(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Check health of tenant's OpenClaw instance."""
    skill_router = SkillRouter(db=db, tenant_id=current_user.tenant_id)
    return skill_router.health_check()


@router.get("/diagnose")
def skill_diagnose(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Step-by-step diagnostic of OpenClaw WebSocket connection."""
    import asyncio
    import json as _json
    import logging

    from app.core.config import settings
    from app.models.tenant_instance import TenantInstance

    logger = logging.getLogger(__name__)
    tenant_id = current_user.tenant_id
    steps = {}

    # Step 1: Resolve instance
    instance = (
        db.query(TenantInstance)
        .filter(
            TenantInstance.tenant_id == tenant_id,
            TenantInstance.instance_type == "openclaw",
            TenantInstance.status == "running",
        )
        .first()
    )
    if not instance:
        return {"steps": {"resolve_instance": {"ok": False, "error": "No running instance"}}}

    steps["resolve_instance"] = {
        "ok": True,
        "instance_id": str(instance.id),
        "internal_url": instance.internal_url,
    }

    # Step 2: Check token
    token = settings.OPENCLAW_GATEWAY_TOKEN
    steps["token_check"] = {
        "ok": bool(token),
        "token_length": len(token) if token else 0,
        "token_prefix": token[:8] + "..." if token and len(token) > 8 else "(empty)",
    }

    ws_url = instance.internal_url.replace("http://", "ws://").replace("https://", "wss://")
    steps["ws_url"] = ws_url

    # Step 3: WebSocket connect + challenge
    async def _diagnose_ws():
        import websockets

        diag = {}

        try:
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                diag["ws_connect"] = {"ok": True}

                # Challenge
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    challenge = _json.loads(raw)
                    diag["challenge"] = {
                        "ok": True,
                        "event": challenge.get("event"),
                        "has_nonce": bool(challenge.get("payload", {}).get("nonce")),
                    }
                    nonce = challenge.get("payload", {}).get("nonce", "")
                except Exception as e:
                    diag["challenge"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                    return diag

                # Auth
                try:
                    connect_req = {
                        "type": "req",
                        "id": f"diag-{uuid.uuid4().hex[:8]}",
                        "method": "connect",
                        "params": {
                            "minProtocol": 3,
                            "maxProtocol": 3,
                            "client": {
                                "id": "servicetsunami-api",
                                "version": "1.0.0",
                                "platform": "linux",
                                "mode": "operator",
                            },
                            "role": "operator",
                            "scopes": ["operator.read", "operator.write"],
                            "auth": {"token": token},
                            "device": {
                                "id": f"st-diag-{tenant_id}",
                                "nonce": nonce,
                            },
                        },
                    }
                    await ws.send(_json.dumps(connect_req))
                    hello_raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    hello = _json.loads(hello_raw)
                    diag["auth"] = {
                        "ok": hello.get("ok", False),
                        "response_type": hello.get("type"),
                        "error": hello.get("error") if not hello.get("ok") else None,
                        "raw_keys": list(hello.keys()),
                    }
                except Exception as e:
                    diag["auth"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        except Exception as e:
            diag["ws_connect"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        return diag

    try:
        ws_diag = asyncio.run(_diagnose_ws())
        steps["websocket"] = ws_diag
    except Exception as e:
        steps["websocket"] = {"error": f"{type(e).__name__}: {e}"}

    return {"steps": steps}
