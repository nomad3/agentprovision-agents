"""Grounded memory-category enforcement (plan 2026-06-08 §8) — PR5.

Typed memory writes/recall posture so stale or overconfident recall is reduced.
This is pure policy logic layered over the existing ``agent_memories.memory_type``
discriminator (review P2-1: extend the vocabulary + add freshness posture, not a
new substrate).

Core invariant (§8): "Memory is not proof by itself when the fact is
time-sensitive, externally mutable, or tied to a commitment status. It can
trigger verification, but it cannot replace it."
"""
from __future__ import annotations

from app.schemas.accountable_learning import MEMORY_CATEGORIES

# Categories that can NEVER stand in as proof of current external state.
_NEVER_PROOF = {"commitment", "stale_context", "emotional_context"}

# Categories that always require verification before confident use.
_ALWAYS_VERIFY = {"commitment", "stale_context"}

# Proof-bearing facts and proof-tied commitments must be kept distinct from
# soft preferences — writing a commitment as a plain fact/preference loses its
# proof path and lifecycle.
_PREFERENCE_LIKE = {"preference", "emotional_context"}


def normalize_memory_category(category: str) -> str:
    """Validate a memory category. Raises ValueError on an unknown category."""
    if category not in MEMORY_CATEGORIES:
        raise ValueError(
            f"unknown memory category {category!r}; expected one of "
            f"{sorted(MEMORY_CATEGORIES)}"
        )
    return category


def is_proof_eligible(category: str, *, time_sensitive: bool = False) -> bool:
    """Whether a memory of this category may be cited as proof of current state.

    A time-sensitive or externally-mutable fact is never proof on its own.
    """
    normalize_memory_category(category)
    if category in _NEVER_PROOF:
        return False
    if category == "fact" and time_sensitive:
        return False
    return True


def requires_verification(category: str, *, time_sensitive: bool = False) -> bool:
    """Whether confident use requires re-verification first."""
    normalize_memory_category(category)
    if category in _ALWAYS_VERIFY:
        return True
    if category == "fact" and time_sensitive:
        return True
    return False


def reject_commitment_as_fact(category: str, *, looks_like_commitment: bool) -> None:
    """Guard: a commitment must not be archived as a plain fact/preference.

    Raises ValueError so the write path fails loud rather than silently losing
    the proof path and lifecycle (plan §8 invariant, PR5 acceptance).
    """
    normalize_memory_category(category)
    if looks_like_commitment and category in ({"fact"} | _PREFERENCE_LIKE):
        raise ValueError(
            "a commitment must be stored as category 'commitment' (with owner, "
            f"due time, and proof path), not {category!r}"
        )


def retrieval_posture(category: str, *, time_sensitive: bool = False) -> dict:
    """Recall-time posture for a memory of this category."""
    proof = is_proof_eligible(category, time_sensitive=time_sensitive)
    verify = requires_verification(category, time_sensitive=time_sensitive)
    return {
        "category": normalize_memory_category(category),
        "proof_eligible": proof,
        "requires_verification": verify,
        # Hedge stale/unproven categories in user-facing language.
        "hedge": (not proof) or verify,
    }


__all__ = [
    "normalize_memory_category",
    "is_proof_eligible",
    "requires_verification",
    "reject_commitment_as_fact",
    "retrieval_posture",
]
