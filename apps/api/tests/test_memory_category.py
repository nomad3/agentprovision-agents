"""PR5 — grounded memory-category enforcement (plan §8)."""
import pytest

from app.services import memory_category as mc


def test_unknown_category_rejected():
    with pytest.raises(ValueError):
        mc.normalize_memory_category("vibes")


def test_commitment_and_stale_are_never_proof():
    assert mc.is_proof_eligible("commitment") is False
    assert mc.is_proof_eligible("stale_context") is False
    assert mc.is_proof_eligible("emotional_context") is False


def test_time_sensitive_fact_is_not_proof():
    assert mc.is_proof_eligible("fact", time_sensitive=True) is False
    assert mc.is_proof_eligible("fact", time_sensitive=False) is True


def test_preference_and_pattern_are_proof_eligible():
    assert mc.is_proof_eligible("preference") is True
    assert mc.is_proof_eligible("pattern") is True
    assert mc.is_proof_eligible("business_context") is True


def test_verification_required_for_commitment_and_stale():
    assert mc.requires_verification("commitment") is True
    assert mc.requires_verification("stale_context") is True
    assert mc.requires_verification("fact", time_sensitive=True) is True
    assert mc.requires_verification("fact") is False
    assert mc.requires_verification("preference") is False


def test_commitment_cannot_be_stored_as_fact_or_preference():
    for cat in ("fact", "preference", "emotional_context"):
        with pytest.raises(ValueError):
            mc.reject_commitment_as_fact(cat, looks_like_commitment=True)
    # storing it correctly as 'commitment' is fine
    mc.reject_commitment_as_fact("commitment", looks_like_commitment=True)
    # a non-commitment fact is fine
    mc.reject_commitment_as_fact("fact", looks_like_commitment=False)


def test_retrieval_posture_hedges_unproven():
    stale = mc.retrieval_posture("stale_context")
    assert stale["proof_eligible"] is False
    assert stale["requires_verification"] is True
    assert stale["hedge"] is True

    solid = mc.retrieval_posture("fact")
    assert solid["proof_eligible"] is True
    assert solid["hedge"] is False
