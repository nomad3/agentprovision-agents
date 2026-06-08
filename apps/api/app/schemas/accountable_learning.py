"""Accountable Learning & Commitment System — typed trace contracts.

Plan: ``docs/plans/2026-06-08-accountable-learning-and-commitment-system.md``.

This module holds the *trace primitives* (frozen dataclasses, validated in
``__post_init__``) that do not need their own table:

- ``OutcomeContract`` — what is expected before non-trivial work starts.
- ``LearningArtifact`` — a distilled, reusable post-task learning record.

It also holds the controlled vocabularies (risk tiers, escalation policies,
red-flag levels, memory categories, outcome quality) shared by the commitment
ledger, the red-flag engine, and the learning write path.

Design follows the established trace-primitive pattern in this repo
(``schemas/reflection.py``, ``schemas/source_grounding.py``): ``tenant_id`` is a
string at the contract boundary (cast at the IO layer), enums are locked
frozensets, and a misspelled value is rejected at construction so a buggy caller
cannot smuggle a bad record past the storage layer.

The durable, lifecycle-bearing commitment ledger is NOT here — it extends the
existing ``commitment_records`` table (model ``models/commitment_record.py``,
schema ``schemas/commitment_record.py``). See plan §6 and the review's P0-1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

# ── Controlled vocabularies ───────────────────────────────────────────
#
# Locked sets. New values MUST be added here AND wired into the consumers
# (red-flag engine, ledger schema, learning write path) in the same PR to
# avoid catalog drift — same discipline as REFLECTION_KINDS.

# Mirrors REFLECTION_RISK_LEVELS so contract + reflection speak one vocabulary.
RISK_THRESHOLDS = frozenset({"low", "medium", "high", "irreversible"})

ESCALATION_POLICIES = frozenset({
    "none",
    "ask_user",
    "notify_owner",
    "supervisor_review",
    "block_action",
})

# Red-flag severity, ordered watch < warn < escalate < block.
RED_FLAG_LEVELS = frozenset({"watch", "warn", "escalate", "block"})
RED_FLAG_LEVEL_ORDER = ("watch", "warn", "escalate", "block")

# Outcome-contract lifecycle. Mirrors the commitment-ledger vocabulary so a
# contract and its commitments stay legible together.
OUTCOME_CONTRACT_STATUSES = frozenset({
    "proposed",
    "active",
    "blocked",
    "done",
    "failed",
    "renegotiated",
    "canceled",
})

# Distilled outcome quality on the learning artifact.
OUTCOME_QUALITIES = frozenset({
    "succeeded",
    "partially_succeeded",
    "failed",
    "inconclusive",
})

CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})

# Grounded memory categories (plan §8). A learning artifact recommends one of
# these as its memory write category; the actual write maps onto the existing
# ``agent_memories.memory_type`` discriminator in PR5.
MEMORY_CATEGORIES = frozenset({
    "fact",
    "preference",
    "commitment",
    "pattern",
    "failed_assumption",
    "business_context",
    "emotional_context",
    "stale_context",
})

# The learning artifact's recommendation can also be "none" (write nothing).
MEMORY_WRITE_RECOMMENDATIONS = MEMORY_CATEGORIES | {"none"}


@dataclass(frozen=True)
class OutcomeContract:
    """What the user/team/agent expects from a task before work starts.

    Trace primitive (plan §5). For non-trivial work Luna should not treat
    "I will do it" as a complete commitment unless this contract has at least a
    goal, an owner, a definition of done, and a proof path. Advisory in PR1; the
    commitment-capture write path (PR2) consumes it.
    """

    tenant_id: str
    contract_id: str
    session_id: str
    created_by_agent_id: str
    requester_ref: str
    goal: str
    expected_outcome: str
    definition_of_done: List[str]
    proof_required: List[str]
    owner_refs: List[str]
    risk_threshold: str
    escalation_policy: str
    status: str
    created_at: str
    updated_at: str
    due_at: Optional[str] = None
    checkpoint_at: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("OutcomeContract.tenant_id is required")
        if not self.goal:
            raise ValueError("OutcomeContract.goal is required")
        if not self.definition_of_done:
            raise ValueError(
                "OutcomeContract.definition_of_done must have >= 1 entry"
            )
        if not self.owner_refs:
            raise ValueError("OutcomeContract.owner_refs must have >= 1 entry")
        if self.risk_threshold not in RISK_THRESHOLDS:
            raise ValueError(
                f"OutcomeContract.risk_threshold {self.risk_threshold!r} not in "
                f"{sorted(RISK_THRESHOLDS)}"
            )
        if self.escalation_policy not in ESCALATION_POLICIES:
            raise ValueError(
                f"OutcomeContract.escalation_policy {self.escalation_policy!r} "
                f"not in {sorted(ESCALATION_POLICIES)}"
            )
        if self.status not in OUTCOME_CONTRACT_STATUSES:
            raise ValueError(
                f"OutcomeContract.status {self.status!r} not in "
                f"{sorted(OUTCOME_CONTRACT_STATUSES)}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LearningArtifact:
    """A distilled, reusable post-task learning record (plan §7).

    Written when a task finishes, fails, gets corrected, reveals a bad
    assumption, or creates a reusable pattern. It is a recommendation, not an
    authority: ``system_update_candidate`` is routed through a review queue
    (PolicyCandidate-style), never auto-applied (plan §14).
    """

    tenant_id: str
    artifact_id: str
    source_refs: List[str]
    task_summary: str
    intended_outcome: str
    observed_outcome: str
    outcome_quality: str
    proof_refs: List[str]
    failed_assumptions: List[str]
    user_corrections: List[str]
    memory_write_recommendation: str
    confidence: str
    created_at: str
    source_contract_id: Optional[str] = None
    source_commitment_id: Optional[str] = None
    reusable_pattern: Optional[str] = None
    anti_pattern: Optional[str] = None
    system_update_candidate: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("LearningArtifact.tenant_id is required")
        if not self.task_summary:
            raise ValueError("LearningArtifact.task_summary is required")
        if self.outcome_quality not in OUTCOME_QUALITIES:
            raise ValueError(
                f"LearningArtifact.outcome_quality {self.outcome_quality!r} not "
                f"in {sorted(OUTCOME_QUALITIES)}"
            )
        if self.memory_write_recommendation not in MEMORY_WRITE_RECOMMENDATIONS:
            raise ValueError(
                "LearningArtifact.memory_write_recommendation "
                f"{self.memory_write_recommendation!r} not in "
                f"{sorted(MEMORY_WRITE_RECOMMENDATIONS)}"
            )
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"LearningArtifact.confidence {self.confidence!r} not in "
                f"{sorted(CONFIDENCE_LEVELS)}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


def red_flag_at_least(level: str, threshold: str) -> bool:
    """True if ``level`` is at or above ``threshold`` in red-flag severity."""
    if level not in RED_FLAG_LEVELS or threshold not in RED_FLAG_LEVELS:
        raise ValueError("unknown red-flag level")
    return RED_FLAG_LEVEL_ORDER.index(level) >= RED_FLAG_LEVEL_ORDER.index(threshold)
