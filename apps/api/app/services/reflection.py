"""Nightly reflection pure-function layer — O1 substrate.

Serialize / deserialize helpers for the agent_memory substrate. Pure
functions only: no DB, no logging side-effects beyond debug.

Mirrors apps/api/app/services/metacog.py — same JSON-with-sort_keys
encoding, same best-effort decode contract, same memory_type
discriminator pattern.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.schemas.reflection import NightlyReflection, ReflectionStep

logger = logging.getLogger(__name__)


# ── Memory type discriminator ─────────────────────────────────────────
REFLECTION_MEMORY_TYPE = "nightly_reflection"
REFLECTION_STEP_MEMORY_TYPE = "reflection_step"


# ── Serialize / deserialize ───────────────────────────────────────────


def serialize_reflection(reflection: NightlyReflection) -> str:
    """JSON-encode a NightlyReflection for agent_memory.content."""
    return json.dumps(reflection.to_dict(), sort_keys=True)


def deserialize_reflection(blob: str) -> Optional[NightlyReflection]:
    """Best-effort decode. Returns None on malformed content rather
    than raising — the caller (read path) skips and logs.

    Captures every plausible decode failure mode:
      - JSONDecodeError: not valid JSON
      - TypeError: shape mismatch (e.g. missing required field)
      - ValueError: invariant breach in __post_init__ (bad kind,
        out-of-range confidence, empty source_memory_ids, oversize
        content)
    """
    try:
        data = json.loads(blob)
        return NightlyReflection(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug(
            "reflection.deserialize_reflection: malformed blob — %s", exc
        )
        return None


def serialize_reflection_step(step: ReflectionStep) -> str:
    """JSON-encode a ReflectionStep for agent_memory.content."""
    return json.dumps(step.to_dict(), sort_keys=True)


def deserialize_reflection_step(blob: str) -> Optional[ReflectionStep]:
    """Best-effort decode for pre-action reflection traces.

    Returns None instead of raising on malformed rows so read paths can
    skip corrupted trace content without breaking operator surfaces.
    """
    try:
        data = json.loads(blob)
        return ReflectionStep(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug(
            "reflection.deserialize_reflection_step: malformed blob — %s",
            exc,
        )
        return None


__all__ = [
    "REFLECTION_MEMORY_TYPE",
    "REFLECTION_STEP_MEMORY_TYPE",
    "serialize_reflection",
    "deserialize_reflection",
    "serialize_reflection_step",
    "deserialize_reflection_step",
]
