"""Activities to auto-create session journals from conversation history (Gap 1)."""
import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import ChatMessage, ChatSession, SessionJournal
from app.services.session_journals import session_journal_service
from app.services.local_inference import summarize_conversation_sync
from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn
async def synthesize_daily_journal(tenant_id: str) -> Optional[str]:
    """
    Create a journal entry from today's conversations.

    This activity:
    1. Reads all messages from today's chat sessions
    2. Summarizes them into a warm, personal narrative
    3. Extracts accomplishments and challenges
    4. Creates a SessionJournal entry

    Runs daily via cron or Temporal scheduler.
    """
    db: Session = SessionLocal()
    try:
        tenant_uuid = uuid.UUID(tenant_id)
        today = date.today()

        # Get all chat messages from today
        messages = db.query(ChatMessage).join(
            ChatSession,
            ChatMessage.session_id == ChatSession.id
        ).filter(
            ChatSession.tenant_id == tenant_uuid,
            func.DATE(ChatMessage.created_at) == today,
        ).order_by(ChatMessage.created_at.asc()).all()

        if not messages:
            logger.info(f"No conversations for tenant {tenant_id} today")
            return None

        # Build conversation text
        conv_text = "\n".join([
            f"[{m.role.upper()}]: {m.content[:500]}"
            for m in messages[:50]  # Limit to last 50 messages
        ])

        # Summarize using local model
        summary = summarize_conversation_sync(conv_text)
        if not summary or len(summary) < 20:
            logger.warning(f"Failed to summarize conversations for tenant {tenant_id}")
            return None

        # Extract key accomplishments/challenges (simple heuristic)
        conv_lower = conv_text.lower()
        accomplishments = []
        challenges = []

        for msg in messages:
            content = msg.content.lower()
            if any(word in content for word in ["done", "completed", "finished", "closed", "resolved", "shipped"]):
                accomplishments.append(msg.content[:100])
            if any(word in content for word in ["problem", "issue", "error", "stuck", "blocked", "failed"]):
                challenges.append(msg.content[:100])

        # Create journal entry
        journal = session_journal_service.create_journal_entry(
            db=db,
            tenant_id=tenant_uuid,
            summary=summary,
            period_start=today,
            period_end=today,
            period_type="day",
            key_accomplishments=accomplishments[:5],
            key_challenges=challenges[:5],
            message_count=len(messages),
        )

        logger.info(f"Created daily journal {journal.id} for tenant {tenant_id}")
        return str(journal.id)

    except ValueError as e:
        logger.error(f"Invalid tenant_id: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to synthesize daily journal: {e}", exc_info=True)
        return None
    finally:
        db.close()


@activity.defn
async def synthesize_weekly_journal(tenant_id: str) -> Optional[str]:
    """
    Create a weekly journal entry from conversations in the past week.

    Runs weekly (e.g., Sunday night) via cron/scheduler.
    """
    db: Session = SessionLocal()
    try:
        tenant_uuid = uuid.UUID(tenant_id)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)  # Sunday

        # Get all chat messages from the week
        messages = db.query(ChatMessage).join(
            ChatSession,
            ChatMessage.session_id == ChatSession.id
        ).filter(
            ChatSession.tenant_id == tenant_uuid,
            func.DATE(ChatMessage.created_at) >= week_start,
            func.DATE(ChatMessage.created_at) <= week_end,
        ).order_by(ChatMessage.created_at.asc()).all()

        if not messages:
            logger.info(f"No conversations for tenant {tenant_id} this week")
            return None

        # Build conversation text (sample for performance)
        conv_text = "\n".join([
            f"[{m.role.upper()}]: {m.content[:200]}"
            for m in messages[::max(1, len(messages)//50)]  # Sample every Nth message
        ])

        # Synthesize with local model
        summary = summarize_conversation_sync(conv_text)
        if not summary or len(summary) < 30:
            logger.warning(f"Failed to synthesize weekly journal for tenant {tenant_id}")
            return None

        # Simple stats extraction
        user_msgs = [m for m in messages if m.role == "user"]
        assistant_msgs = [m for m in messages if m.role == "assistant"]

        # Create weekly journal
        journal = session_journal_service.create_journal_entry(
            db=db,
            tenant_id=tenant_uuid,
            summary=summary,
            period_start=week_start,
            period_end=week_end,
            period_type="week",
            message_count=len(messages),
            activity_score=min(100, len(user_msgs) * 10),  # Simple activity score
        )

        logger.info(f"Created weekly journal {journal.id} for tenant {tenant_id}")
        return str(journal.id)

    except ValueError as e:
        logger.error(f"Invalid tenant_id: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to synthesize weekly journal: {e}", exc_info=True)
        return None
    finally:
        db.close()
