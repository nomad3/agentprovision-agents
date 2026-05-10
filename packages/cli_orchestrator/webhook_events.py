"""Webhook event-name constants + payload builder — Phase 3 commit 5.

Design §11.3 specifies six event types. We expose the names as
constants here so subscribers register against ``EVENT_*`` rather
than string-typing each one. ``to_webhook_payload(event, metadata)``
delegates to ``ExecutionMetadata.to_webhook_payload(event)`` — kept
here as a convenience wrapper so callers don't have to import the
metadata module just to shape a payload.

The 6 events:

  - ``execution.started``           — at top of execute() after recursion gate passes
  - ``execution.attempt_failed``    — per-platform non-success result (BEFORE policy.decide)
  - ``execution.fallback_triggered`` — when decide() returns action="fallback"
  - ``execution.succeeded``         — _finalise_success
  - ``execution.failed``            — _finalise_stop AND chain-exhausted terminal exit
  - ``execution.heartbeat_missed``  — leaf-side (commit 8)

Subscribers configure these via ``register_webhook`` MCP tool (already
shipped). ``events: ["execution.*"]`` already supports prefix matching.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .metadata import ExecutionMetadata


# ── Event name constants ────────────────────────────────────────────────

EVENT_STARTED = "execution.started"
EVENT_ATTEMPT_FAILED = "execution.attempt_failed"
EVENT_FALLBACK_TRIGGERED = "execution.fallback_triggered"
EVENT_SUCCEEDED = "execution.succeeded"
EVENT_FAILED = "execution.failed"
EVENT_HEARTBEAT_MISSED = "execution.heartbeat_missed"

ALL_EVENTS: tuple[str, ...] = (
    EVENT_STARTED,
    EVENT_ATTEMPT_FAILED,
    EVENT_FALLBACK_TRIGGERED,
    EVENT_SUCCEEDED,
    EVENT_FAILED,
    EVENT_HEARTBEAT_MISSED,
)


def to_webhook_payload(event: str, metadata: "ExecutionMetadata") -> dict[str, Any]:
    """Convenience builder — delegates to ExecutionMetadata.to_webhook_payload.

    Kept here so callers can import a single event-shaping module rather
    than reaching into the metadata dataclass directly. Truncation rules
    (512B for non-failed, 4KB for execution.failed) are still enforced
    inside ``ExecutionMetadata.to_webhook_payload``.
    """
    if event not in ALL_EVENTS:
        # Defensive — emit anyway with a simple shape.
        return {"event": event, "run_id": getattr(metadata, "run_id", None)}
    return metadata.to_webhook_payload(event)


__all__ = [
    "EVENT_STARTED",
    "EVENT_ATTEMPT_FAILED",
    "EVENT_FALLBACK_TRIGGERED",
    "EVENT_SUCCEEDED",
    "EVENT_FAILED",
    "EVENT_HEARTBEAT_MISSED",
    "ALL_EVENTS",
    "to_webhook_payload",
]
