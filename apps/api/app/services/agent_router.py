"""Agent Router — routes messages to CLI platforms.

Phase 1: Deterministic routing (tenant default + agent affinity).
Phase 3: RL-driven routing added on top.
"""
import logging
import uuid
from typing import Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session

from app.models.tenant_features import TenantFeatures
from app.services.cli_session_manager import run_agent_session

logger = logging.getLogger(__name__)

# Default agent for each channel
CHANNEL_AGENT_MAP = {
    "whatsapp": "luna",
    "web": "luna",
}


def route_and_execute(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
    channel: str = "web",
    sender_phone: str = None,
    agent_slug: str = None,
    conversation_summary: str = "",
    image_b64: str = "",
    image_mime: str = "",
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Route message to the appropriate CLI platform and execute.

    Phase 1 implementation: Deterministic routing based on tenant default
    and channel affinity. No RL yet.

    Args:
        db: SQLAlchemy database session.
        tenant_id: UUID of the tenant.
        user_id: UUID of the authenticated user.
        message: The user's message to process.
        channel: Communication channel (default "web"). Used to infer agent
            if agent_slug not specified.
        sender_phone: Sender's phone number (relevant for WhatsApp channel).
        agent_slug: Explicit agent slug. If not provided, defaults are applied
            based on channel.
        conversation_summary: Brief summary of prior conversation context.

    Returns:
        Tuple of (response_text, metadata).
        response_text is the agent's response (or None on failure).
        metadata includes agent info, platform, token usage, and error details.
    """
    # Apply channel-based agent default if not explicitly specified
    if not agent_slug:
        agent_slug = CHANNEL_AGENT_MAP.get(channel, "luna")

    # Load tenant features to determine the CLI platform preference
    features = db.query(TenantFeatures).filter(
        TenantFeatures.tenant_id == tenant_id
    ).first()

    # Default platform is claude_code; allow per-tenant override via features
    platform = "claude_code"
    if features and hasattr(features, 'default_cli_platform') and features.default_cli_platform:
        platform = features.default_cli_platform

    logger.info(
        "Routing: tenant=%s agent=%s platform=%s channel=%s",
        str(tenant_id)[:8], agent_slug, platform, channel,
    )

    # Execute on the selected platform
    if platform == "claude_code":
        return run_agent_session(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_slug=agent_slug,
            message=message,
            channel=channel,
            sender_phone=sender_phone,
            conversation_summary=conversation_summary,
            image_b64=image_b64,
            image_mime=image_mime,
        )

    # Future: gemini_cli, codex_cli, etc.
    return None, {"error": f"Platform '{platform}' not yet supported"}
