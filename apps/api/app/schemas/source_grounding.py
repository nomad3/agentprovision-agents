"""Source-grounding labels — PR 2 of the trusted-teammate engines plan.

A `GroundedClaim` is the small honesty primitive behind safety invariant #1
(*evidence before interpretation*): it forces a strategic suggestion or a line
in a generated plan to declare HOW it is grounded, separating what is copied
from a source from what is merely inferred or speculative.

The four labels (canonical, plan §5 PR 2):

  - ``copied``      — directly grounded in a cited source (quote/extract).
  - ``adapted``     — transformed from cited local context.
  - ``inferred``    — derived from evidence, but not explicitly present.
  - ``speculative`` — a proposed idea requiring validation.

Load-bearing invariant: a claim that asserts it is grounded in a source
(``copied`` / ``adapted``) MUST carry >= 1 ``evidence_ref``. You cannot claim
to have copied or adapted something from nowhere — that is exactly the
hallucination this primitive exists to make visible. ``inferred`` and
``speculative`` may stand without explicit sources, but downstream rendering
must never present them to a user as fact (enforced by
``services/source_grounding.py``).

This is a trace/labelling primitive only: it does not persist, does not block,
and is not wired into any runtime hot path. It mirrors the ReflectionStep
dataclass shape (``schemas/reflection.py``) so reviewers see one consistent
contract across the engines.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List

# ── Canonical grounding labels (locked set) ───────────────────────────
GROUNDING_LABELS = frozenset({
    "copied",
    "adapted",
    "inferred",
    "speculative",
})

# Labels that assert grounding in a concrete source and therefore REQUIRE
# at least one evidence_ref.
SOURCE_BACKED_LABELS = frozenset({"copied", "adapted"})

RISK_IF_WRONG_LEVELS = frozenset({"low", "medium", "high", "irreversible"})


@dataclass(frozen=True)
class GroundedClaim:
    """A single labelled claim separating evidence from inference."""

    label: str
    claim: str
    evidence_refs: List[str]
    confidence: float
    risk_if_wrong: str

    def __post_init__(self) -> None:
        if self.label not in GROUNDING_LABELS:
            raise ValueError(
                f"label must be one of {sorted(GROUNDING_LABELS)}, "
                f"got {self.label!r}"
            )
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ValueError("claim must be a non-empty string")
        if not isinstance(self.evidence_refs, list):
            raise ValueError("evidence_refs must be a list")
        if any(
            not isinstance(ref, str) or not ref.strip()
            for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must contain non-empty strings")
        # Evidence-before-interpretation: a claim that asserts it is grounded
        # in a source cannot stand with no source cited.
        if self.label in SOURCE_BACKED_LABELS and len(self.evidence_refs) == 0:
            raise ValueError(
                f"label {self.label!r} asserts grounding in a source and "
                "requires at least one evidence_ref"
            )
        # bool is an int subclass; reject it explicitly so a stray True/False
        # can't masquerade as a confidence value.
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ValueError("confidence must be a number")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.risk_if_wrong not in RISK_IF_WRONG_LEVELS:
            raise ValueError(
                f"risk_if_wrong must be one of {sorted(RISK_IF_WRONG_LEVELS)}, "
                f"got {self.risk_if_wrong!r}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = [
    "GROUNDING_LABELS",
    "SOURCE_BACKED_LABELS",
    "RISK_IF_WRONG_LEVELS",
    "GroundedClaim",
]
