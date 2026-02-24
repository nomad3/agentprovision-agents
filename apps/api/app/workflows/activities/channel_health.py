"""
Temporal activities for channel health monitoring.

These activities run in the same process as the WhatsApp service,
calling its methods directly.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List

from temporalio import activity

from app.db.session import SessionLocal
from app.models.channel_account import ChannelAccount

logger = logging.getLogger(__name__)


@activity.defn
async def check_channel_health(tenant_id: str) -> Dict[str, Any]:
    """Check all WhatsApp channel accounts for a tenant. Returns status report."""
    from app.services.whatsapp_service import whatsapp_service

    db = SessionLocal()
    try:
        accounts = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.tenant_id == tenant_id,
                ChannelAccount.channel_type == "whatsapp",
                ChannelAccount.enabled == True,
            )
            .all()
        )

        connected: List[str] = []
        disconnected: List[str] = []

        for acct in accounts:
            key = whatsapp_service._make_key(str(acct.tenant_id), acct.account_id)
            status = whatsapp_service._statuses.get(key, "disconnected")
            if status == "connected":
                connected.append(acct.account_id)
            else:
                disconnected.append(acct.account_id)

        return {
            "total": len(accounts),
            "connected": connected,
            "disconnected": disconnected,
            "checked_at": datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


@activity.defn
async def reconnect_channel(tenant_id: str, account_id: str) -> Dict[str, Any]:
    """Reconnect a disconnected WhatsApp channel."""
    from app.services.whatsapp_service import whatsapp_service

    try:
        result = await whatsapp_service.reconnect(tenant_id, account_id)
        return {"success": True, "result": result}
    except Exception as e:
        logger.exception(f"Failed to reconnect {tenant_id[:8]}:{account_id}")
        return {"success": False, "error": str(e)}


@activity.defn
async def update_channel_health_status(
    tenant_id: str, status_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Update channel_accounts health status in DB."""
    db = SessionLocal()
    try:
        for account_id in status_report.get("disconnected", []):
            acct = (
                db.query(ChannelAccount)
                .filter(
                    ChannelAccount.tenant_id == tenant_id,
                    ChannelAccount.channel_type == "whatsapp",
                    ChannelAccount.account_id == account_id,
                )
                .first()
            )
            if acct:
                acct.status = "disconnected"
                acct.disconnected_at = datetime.utcnow()
                acct.reconnect_attempts = (acct.reconnect_attempts or 0) + 1

        for account_id in status_report.get("connected", []):
            acct = (
                db.query(ChannelAccount)
                .filter(
                    ChannelAccount.tenant_id == tenant_id,
                    ChannelAccount.channel_type == "whatsapp",
                    ChannelAccount.account_id == account_id,
                )
                .first()
            )
            if acct and acct.status != "connected":
                acct.status = "connected"
                acct.connected_at = datetime.utcnow()
                acct.reconnect_attempts = 0

        db.commit()
        return {"updated": True}
    except Exception:
        db.rollback()
        logger.exception("Failed to update channel health status")
        return {"updated": False}
    finally:
        db.close()
