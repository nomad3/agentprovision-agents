"""
Commitment extractor — auto-extract predictions/promises from Luna responses (Gap 3: Stakes).

Flow:
  1. After Luna response: extract_commitments_from_response()
     → identifies prediction/promise sentences
     → creates CommitmentRecord with type="prediction", state="open"
  2. Nightly: check_commitment_resolution()
     → for due commitments, ask "Did this work?"
     → user feedback → fulfilled_at or broken_at
  3. On morning briefing: build_stakes_context()
     → "You have 3 open commitments, 1 overdue"
     → increases accountability/awareness
"""

import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.commitment_record import CommitmentRecord

logger = logging.getLogger(__name__)

# Patterns that indicate Luna is making a commitment/prediction
_COMMITMENT_PATTERNS = [
    (r"(?:i'll|i will|should|we'll|we will) (?:help|fix|solve|improve|increase|decrease|ensure)", "promise"),
    (r"this (?:will|should|can|might) (?:help|work|improve|resolve|fix|increase)", "prediction"),
    (r"(?:expect|predict|think|believe) (?:this|that|it) (?:will|should|might) (?:work|help|improve)", "prediction"),
    (r"(?:next step|action item|follow.?up|todo) (?:is|are|should be|would be)", "action_item"),
    (r"(?:i promise|i commit|we commit) to (?:send|reach|follow|schedule|create)", "promise"),
    (r"(?:let me|let's) (?:follow up|check in|review|reconnect) (?:soon|next|tomorrow|in \d+ (?:days|hours))", "promise"),
    (r"(?:by|before) (?:tomorrow|next week|end of day|eow|end of week)", "time_bound"),
]

# Confidence scores for different pattern types
_CONFIDENCE_SCORES = {
    "promise": 0.95,
    "prediction": 0.75,
    "action_item": 0.85,
    "time_bound": 0.90,
}


def extract_commitments_from_response(
    db: Session,
    tenant_id: uuid.UUID,
    response_text: str,
    message_id: Optional[uuid.UUID] = None,
    session_id: Optional[uuid.UUID] = None,
) -> List[CommitmentRecord]:
    """
    Parse Luna's response for commitments/predictions and create CommitmentRecord entries.
    Returns list of created commitment records.
    """
    commitments = _parse_commitments(response_text)
    if not commitments:
        return []

    records = []
    for text, ctype, confidence in commitments:
        # Estimate due date from text if present
        due_at = _extract_due_date(text)

        commitment = CommitmentRecord(
            tenant_id=tenant_id,
            owner_agent_slug="luna",
            title=text[:200],
            description=text,
            commitment_type="prediction",  # All auto-extracted are predictions
            state="open",
            priority="normal",
            source_type="auto_extract",
            source_ref={"pattern": ctype, "confidence": confidence},
            due_at=due_at,
        )
        db.add(commitment)
        db.flush()

        records.append(commitment)

    if records:
        db.commit()
        logger.info(f"Extracted {len(records)} commitments for tenant {tenant_id}")

    return records


def build_stakes_context(
    db: Session,
    tenant_id: uuid.UUID,
) -> str:
    """
    Build a text block for Luna's system prompt showing open commitments.
    Gap 3: Increases accountability by making Luna aware of her promises.
    """
    # Get open and overdue commitments
    now = datetime.utcnow()

    open_commitments = db.query(CommitmentRecord).filter(
        CommitmentRecord.tenant_id == tenant_id,
        CommitmentRecord.state == "open",
    ).all()

    overdue = [c for c in open_commitments if c.due_at and c.due_at < now]

    if not open_commitments:
        return ""

    lines = [f"## Your Open Commitments ({len(open_commitments)} total)"]

    if overdue:
        lines.append(f"⚠️ **{len(overdue)} OVERDUE**")
        for c in overdue[:3]:
            days_overdue = (now - c.due_at).days
            lines.append(f"  - {c.title[:50]}... (due {days_overdue}d ago)")

    upcoming = [c for c in open_commitments if c.due_at and c.due_at >= now]
    if upcoming:
        lines.append(f"\n📌 **{len(upcoming)} Upcoming**")
        for c in upcoming[:3]:
            days_until = (c.due_at - now).days
            lines.append(f"  - {c.title[:50]}... (due in {days_until}d)")

    lines.append("\nRemember these commitments as you respond. Accountability matters.")

    return "\n".join(lines)


def get_commitment_stats(
    db: Session,
    tenant_id: uuid.UUID,
    days: int = 30,
) -> dict:
    """
    Return fulfillment stats over last N days for system prompt injection.
    Shows Luna how often she follows through.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    all_commitments = db.query(CommitmentRecord).filter(
        CommitmentRecord.tenant_id == tenant_id,
        CommitmentRecord.created_at >= cutoff,
    ).all()

    if not all_commitments:
        return {}

    fulfilled = len([c for c in all_commitments if c.state == "fulfilled"])
    broken = len([c for c in all_commitments if c.state == "broken"])
    open_count = len([c for c in all_commitments if c.state == "open"])

    total = fulfilled + broken + open_count
    if total == 0:
        return {}

    return {
        "total": total,
        "fulfilled": fulfilled,
        "broken": broken,
        "open": open_count,
        "fulfillment_rate": round(fulfilled / (fulfilled + broken), 2) if (fulfilled + broken) > 0 else 0,
    }


# --- Helpers ---

def _parse_commitments(text: str) -> List[Tuple[str, str, float]]:
    """Extract commitment/prediction sentences. Returns (text, type, confidence)."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    results = []
    seen = set()

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15 or len(sentence) > 300:
            continue

        lower = sentence.lower()
        for pattern, ctype in _COMMITMENT_PATTERNS:
            if re.search(pattern, lower):
                key = sentence[:60]
                if key not in seen:
                    seen.add(key)
                    confidence = _CONFIDENCE_SCORES.get(ctype, 0.7)
                    results.append((sentence, ctype, confidence))
                break

    return results


def _extract_due_date(text: str) -> Optional[datetime]:
    """Extract due date from commitment text if present."""
    now = datetime.utcnow()
    lower = text.lower()

    # tomorrow
    if "tomorrow" in lower:
        return now + timedelta(days=1)

    # "in N days/hours"
    match = re.search(r"in (\d+)\s*(days?|hours?)", lower)
    if match:
        count = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("day"):
            return now + timedelta(days=count)
        elif unit.startswith("hour"):
            return now + timedelta(hours=count)

    # "next week"
    if "next week" in lower:
        return now + timedelta(days=7)

    # "end of day / eod"
    if "end of day" in lower or "eod" in lower:
        return now + timedelta(days=1)  # EOD today treated as EOD tomorrow for intent

    # "this week"
    if "this week" in lower:
        return now + timedelta(days=5)

    return None
