"""Source-grounding service helpers — PR 2 trusted-teammate engines.

Stateless helpers around ``GroundedClaim`` that enforce the two user-facing
acceptance criteria of the plan (§5 PR 2):

  - user-facing output must never present a ``speculative`` (or ``inferred``)
    idea as fact — ``render_claim_for_user`` prepends a caveat for those;
  - generated plans expose their overall confidence and risk-if-wrong —
    ``summarize_grounding`` reports the weakest link across a set of claims.

Pure functions, no IO, no persistence, not wired into any runtime path.
"""
from __future__ import annotations

from typing import List

from app.schemas.source_grounding import (
    GROUNDING_LABELS,
    SOURCE_BACKED_LABELS,
    GroundedClaim,
)

# Severity ordering for risk_if_wrong, so a plan's "weakest link" is well-defined.
_RISK_ORDER = ("low", "medium", "high", "irreversible")

# Human-readable caveats for labels that are NOT grounded in a cited source.
_CAVEATS = {
    "inferred": "Inferred — derived from evidence, not directly stated.",
    "speculative": (
        "Speculative — a proposed idea requiring validation, not an "
        "established fact."
    ),
}


def is_source_backed(label: str) -> bool:
    """Whether the label asserts grounding in a concrete cited source."""
    return label in SOURCE_BACKED_LABELS


def requires_user_facing_caveat(label: str) -> bool:
    """Whether user-facing output must caveat this label (inferred/speculative)."""
    return label in (GROUNDING_LABELS - SOURCE_BACKED_LABELS)


def user_facing_caveat(label: str) -> str:
    """Caveat string for a label, or '' when no caveat is required."""
    return _CAVEATS.get(label, "")


def render_claim_for_user(claim: GroundedClaim) -> str:
    """Render a claim for user-facing output.

    Source-backed claims (copied/adapted) render verbatim; inferred and
    speculative claims are prefixed with their caveat so they can never be
    presented to a user as established fact (acceptance criterion + safety
    invariant #1).
    """
    caveat = user_facing_caveat(claim.label)
    if caveat:
        return f"({caveat}) {claim.claim}"
    return claim.claim


def summarize_grounding(claims: List[GroundedClaim]) -> dict:
    """Report the weakest link across a set of claims for a plan/recommendation.

    Returns overall confidence (the minimum), the maximum risk-if-wrong, whether
    any claim is speculative, and a per-label histogram. An empty set is safe
    (no speculation, undefined confidence/risk).
    """
    if not claims:
        return {
            "min_confidence": None,
            "max_risk_if_wrong": None,
            "has_speculative": False,
            "counts": {},
        }
    counts: dict = {}
    for c in claims:
        counts[c.label] = counts.get(c.label, 0) + 1
    max_risk = max(claims, key=lambda c: _RISK_ORDER.index(c.risk_if_wrong))
    return {
        "min_confidence": min(c.confidence for c in claims),
        "max_risk_if_wrong": max_risk.risk_if_wrong,
        "has_speculative": any(c.label == "speculative" for c in claims),
        "counts": counts,
    }


__all__ = [
    "is_source_backed",
    "requires_user_facing_caveat",
    "user_facing_caveat",
    "render_claim_for_user",
    "summarize_grounding",
]
