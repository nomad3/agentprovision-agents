"""Nightly reflection schema — O1 substrate (offline synthesis track).

A `NightlyReflection` is a single trace persisted at the end of an
offline-synthesis pass: the agent's structured "next-morning note"
about a pattern, idea, tension, planned move, or creative thread it
extracted from the day's memories.

Citation is the load-bearing invariant — every reflection MUST point
at >= 1 source memory_id. The synthesis loop's whole credibility
depends on it: a reflection without sources is hallucination, and the
morning-review surface refuses to display it. Validated in
`__post_init__` so a buggy caller can't smuggle in an empty list and
have the storage layer notice too late.

Content is capped at 500 chars — the canonical design (§3.6) treats
reflections as headline-shaped notes, not essays. Long-form expansion
lives in O2 workflows once the substrate is exercised.

Mirrors the M1 metacog schema shape (apps/api/app/schemas/metacog.py)
so the IO layer (reflection_io.py) can wear the same tenant-boundary
discipline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List

# ── Allowed reflection kinds ──────────────────────────────────────────
#
# Locked set — a misspelled kind would silently drop the reflection
# from the morning-review filters that consume this. New kinds added
# here MUST also be wired into the synthesis workflow (O2) in the same
# PR to avoid catalog drift.
REFLECTION_KINDS = frozenset({
    "risk",         # pattern that looks like an incident waiting to happen
    "idea",         # novel combination from observed patterns
    "tension",      # unresolved blackboard / disagreement thread
    "next_move",    # prioritised action for tomorrow
    "creative",     # story/worldbuilding, opt-in per tenant
})

# Cap matches the canonical design's headline-shape convention.
MAX_CONTENT_LEN = 500


# ── Pre-action reflection step contract ───────────────────────────────
#
# PR 1 of the trusted-teammate engines plan. Unlike NightlyReflection,
# this is a turn-time trace: before a high-friction action, the agent
# records what it thinks the user wants, what evidence it has, what it
# is assuming, and which metacognitive affordance downstream policy
# should inspect. Trace-only in PR 1; no automatic blocking.
REFLECTION_ACTION_KINDS = frozenset({
    "repo_edit_dirty_worktree",
    "pr_creation",
    "tool_failure_retry",
    "user_specific_claim",
    "high_stakes_advice",
    "external_side_effect",
})

REFLECTION_UNCERTAINTY_LEVELS = frozenset({"low", "medium", "high"})
REFLECTION_RISK_LEVELS = frozenset({"low", "medium", "high", "irreversible"})
REFLECTION_AFFORDANCES = frozenset({
    "commit",
    "verify",
    "ask_user",
    "delegate",
    "escalate",
})


@dataclass(frozen=True)
class ReflectionStep:
    """Structured pre-action reflection for high-friction actions.

    The shape intentionally separates evidence from assumptions. This
    is the small connective contract between metacognition, affect,
    teamwork, and trust. It is persisted as an agent_memory trace in
    PR 1 and remains advisory until later behavior PRs consume it.
    """

    tenant_id: str
    agent_id: str
    session_id: str
    action_kind: str
    user_intent: str
    evidence_refs: List[str]
    assumptions: List[str]
    uncertainty: str
    risk_level: str
    required_checks: List[str]
    recommended_affordance: str
    created_at: str

    def __post_init__(self) -> None:
        if self.action_kind not in REFLECTION_ACTION_KINDS:
            raise ValueError(
                "action_kind must be one of "
                f"{sorted(REFLECTION_ACTION_KINDS)}, got "
                f"{self.action_kind!r}"
            )
        if not isinstance(self.user_intent, str) or not self.user_intent.strip():
            raise ValueError("user_intent must be a non-empty string")
        if not isinstance(self.evidence_refs, list):
            raise ValueError("evidence_refs must be a list")
        if not isinstance(self.assumptions, list):
            raise ValueError("assumptions must be a list")
        if self.uncertainty not in REFLECTION_UNCERTAINTY_LEVELS:
            raise ValueError(
                "uncertainty must be one of "
                f"{sorted(REFLECTION_UNCERTAINTY_LEVELS)}, got "
                f"{self.uncertainty!r}"
            )
        if self.risk_level not in REFLECTION_RISK_LEVELS:
            raise ValueError(
                "risk_level must be one of "
                f"{sorted(REFLECTION_RISK_LEVELS)}, got "
                f"{self.risk_level!r}"
            )
        if not isinstance(self.required_checks, list) or len(self.required_checks) == 0:
            raise ValueError("required_checks must be a non-empty list")
        if self.recommended_affordance not in REFLECTION_AFFORDANCES:
            raise ValueError(
                "recommended_affordance must be one of "
                f"{sorted(REFLECTION_AFFORDANCES)}, got "
                f"{self.recommended_affordance!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NightlyReflection:
    """One synthesised note from an offline-synthesis pass.

    Required fields:
      - tenant_id / agent_id — UUIDs (as strings; cast at the IO layer)
      - day                 — YYYY-MM-DD UTC, the day the synthesis pass
                              was about (NOT the run-time, which is `ts`)
      - kind                — one of REFLECTION_KINDS
      - content             — natural language, <= 500 chars
      - source_memory_ids   — REQUIRED non-empty; citation discipline
      - confidence          — in [0, 1]
      - ts                  — ISO-8601 UTC of when the reflection was
                              written (i.e. the synthesis run-time)
    """

    tenant_id: str
    agent_id: str
    day: str
    kind: str
    content: str
    source_memory_ids: List[str]
    confidence: float
    ts: str

    def __post_init__(self) -> None:
        if self.kind not in REFLECTION_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(REFLECTION_KINDS)}, "
                f"got {self.kind!r}"
            )
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string")
        if len(self.content) > MAX_CONTENT_LEN:
            raise ValueError(
                f"content must be <= {MAX_CONTENT_LEN} chars, "
                f"got {len(self.content)}"
            )
        if not isinstance(self.source_memory_ids, list) or len(self.source_memory_ids) == 0:
            # The whole point of the offline-synthesis track is that
            # every reflection cites its receipts. An empty list means
            # no receipts; refuse to construct.
            raise ValueError(
                "source_memory_ids must be a non-empty list — "
                "every reflection requires at least one source memory "
                "(citation discipline, canonical design §3.6)"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = [
    "REFLECTION_KINDS",
    "MAX_CONTENT_LEN",
    "REFLECTION_ACTION_KINDS",
    "REFLECTION_UNCERTAINTY_LEVELS",
    "REFLECTION_RISK_LEVELS",
    "REFLECTION_AFFORDANCES",
    "ReflectionStep",
    "NightlyReflection",
]
