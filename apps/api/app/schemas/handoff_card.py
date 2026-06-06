"""Team handoff cards — PR 3 of the trusted-teammate engines plan.

A `HandoffCard` is the typed contract for transferring a task between agents
(Luna -> Claudia -> specialist). It exists so a receiving agent can pick up
work *without replaying the whole session*: the card states the objective, the
system in scope, the source docs, the constraints, the explicit non-goals, the
expected artifact, what the reviewer should focus on, and the stop conditions.

Two invariants make it safe rather than decorative:

  - **stop_conditions is required and non-empty.** A handoff with no stop
    conditions is how an agent runs past its mandate; the receiver must always
    know when to halt and escalate.
  - **reviewer_focus is required and non-empty.** The card doubles as the review
    contract (Code Reviewer / Substrate Sentinel reference it), so it must say
    what to scrutinise.

Self-other scope (safety invariant #4) is explicit: every card names
`from_agent` and `to_agent`, and a handoff must cross between two different
parties. Tenant scope (#6) rides on `tenant_id`.

Trace/contract primitive only: no persistence, no auto-dispatch, not wired into
any runtime hot path. Mirrors the ReflectionStep / GroundedClaim dataclass
shape so reviewers see one consistent contract across the engines.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List


@dataclass(frozen=True)
class HandoffCard:
    """Typed Luna -> Claudia -> specialist handoff contract."""

    tenant_id: str
    from_agent: str
    to_agent: str
    objective: str
    system: str  # repo or system in scope
    source_docs: List[str]
    constraints: List[str]
    non_goals: List[str]
    expected_artifact: str
    reviewer_focus: List[str]
    stop_conditions: List[str]
    created_at: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "from_agent", "to_agent", "objective",
                     "system", "expected_artifact"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.from_agent == self.to_agent:
            raise ValueError(
                "a handoff must cross between two different agents "
                f"(from_agent == to_agent == {self.from_agent!r})"
            )
        for name in ("source_docs", "constraints", "non_goals",
                     "reviewer_focus", "stop_conditions"):
            if not isinstance(getattr(self, name), list):
                raise ValueError(f"{name} must be a list")
        # The card is the receiver's mandate: it must say when to stop and what
        # the reviewer should scrutinise, or it is not a safe handoff contract.
        if len(self.stop_conditions) == 0:
            raise ValueError("stop_conditions must be a non-empty list")
        if len(self.reviewer_focus) == 0:
            raise ValueError("reviewer_focus must be a non-empty list")

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = ["HandoffCard"]
