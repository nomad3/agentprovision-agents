"""Auto-quality scorer — rates every agent response using local Ollama model.

Runs asynchronously after each chat response is returned to the user.
Feeds scores back into the RL system as implicit rewards.

This replaces manual thumbs up/down as the primary training signal,
increasing RL data from ~43 manual ratings to hundreds of auto-scored
experiences per day.
"""

import asyncio
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def score_and_log_async(
    tenant_id: uuid.UUID,
    user_message: str,
    agent_response: str,
    trajectory_id: Optional[uuid.UUID] = None,
):
    """Fire-and-forget: score response quality and log RL reward.

    Call this AFTER returning the response to the user.
    Runs in background thread — never blocks the response.
    """
    import threading
    threading.Thread(
        target=lambda: asyncio.run(_score_and_log(tenant_id, user_message, agent_response, trajectory_id)),
        daemon=True,
    ).start()


async def _score_and_log(
    tenant_id: uuid.UUID,
    user_message: str,
    agent_response: str,
    trajectory_id: Optional[uuid.UUID] = None,
):
    """Score the response and log as RL reward."""
    from app.services.local_inference import score_response_quality, is_available

    logger.info("Auto-quality scorer: starting for tenant %s", str(tenant_id)[:8])

    # Check if Ollama is available
    if not await is_available():
        logger.info("Auto-quality scorer: Ollama not available — skipping")
        return

    # Score the response
    result = await score_response_quality(user_message, agent_response)
    if not result:
        logger.debug("Auto-quality scoring returned no result")
        return

    score = result["score"]
    reasoning = result.get("reasoning", "")

    # Map 1-5 score to RL reward: 1→-1.0, 2→-0.5, 3→0.0, 4→+0.5, 5→+1.0
    reward = (score - 3) / 2.0

    logger.info(
        "Auto-quality score: %d/5 (reward=%.2f) — %s",
        score, reward, reasoning[:80],
    )

    # Log as RL experience: create, then assign reward
    try:
        from app.db.session import SessionLocal
        from app.services import rl_experience_service

        db = SessionLocal()
        try:
            exp = rl_experience_service.log_experience(
                db,
                tenant_id=tenant_id,
                trajectory_id=trajectory_id or uuid.uuid4(),
                step_index=0,
                decision_point="response_generation",
                state={
                    "user_message": user_message[:200],
                    "response_length": len(agent_response),
                },
                action={
                    "response_preview": agent_response[:100],
                },
                state_text=f"User: {user_message[:100]} → Response: {agent_response[:100]}",
            )
            # Now assign the reward
            rl_experience_service.assign_reward(
                db,
                experience_id=exp.id,
                reward=reward,
                reward_components={
                    "score": score,
                    "reasoning": reasoning,
                    "model": result.get("model", ""),
                },
                reward_source="auto_quality",
            )
            logger.info("Auto-quality RL experience saved: id=%s reward=%.2f", str(exp.id)[:8], reward)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to log auto-quality RL experience: %s", e)
