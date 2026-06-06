"""Tests for PR 2 — source-grounding labels (trusted-teammate engines)."""
import pytest

from app.schemas.source_grounding import (
    GROUNDING_LABELS,
    RISK_IF_WRONG_LEVELS,
    GroundedClaim,
)


def test_grounding_labels_are_the_four_canonical():
    assert GROUNDING_LABELS == {"copied", "adapted", "inferred", "speculative"}


def test_risk_levels_match_reflection_contract():
    assert RISK_IF_WRONG_LEVELS == {"low", "medium", "high", "irreversible"}


def test_copied_requires_evidence():
    # You cannot claim to have copied from a source with no source cited.
    with pytest.raises(ValueError):
        GroundedClaim(
            label="copied", claim="x", evidence_refs=[],
            confidence=0.9, risk_if_wrong="low",
        )


def test_adapted_requires_evidence():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="adapted", claim="x", evidence_refs=[],
            confidence=0.8, risk_if_wrong="low",
        )


def test_inferred_allowed_without_explicit_source():
    c = GroundedClaim(
        label="inferred", claim="derived from the trend", evidence_refs=[],
        confidence=0.6, risk_if_wrong="low",
    )
    assert c.label == "inferred"


def test_speculative_allowed_without_source():
    c = GroundedClaim(
        label="speculative", claim="maybe we should try X", evidence_refs=[],
        confidence=0.3, risk_if_wrong="medium",
    )
    assert c.label == "speculative"


def test_unknown_label_rejected():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="guessed", claim="x", evidence_refs=[],
            confidence=0.5, risk_if_wrong="low",
        )


def test_empty_claim_rejected():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="speculative", claim="   ", evidence_refs=[],
            confidence=0.5, risk_if_wrong="low",
        )


def test_confidence_must_be_in_unit_interval():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="inferred", claim="x", evidence_refs=[],
            confidence=1.5, risk_if_wrong="low",
        )
    with pytest.raises(ValueError):
        GroundedClaim(
            label="inferred", claim="x", evidence_refs=[],
            confidence=-0.1, risk_if_wrong="low",
        )


def test_unknown_risk_if_wrong_rejected():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="inferred", claim="x", evidence_refs=[],
            confidence=0.5, risk_if_wrong="catastrophic",
        )


def test_evidence_refs_must_be_a_list():
    with pytest.raises(ValueError):
        GroundedClaim(
            label="copied", claim="x", evidence_refs="doc#1",  # type: ignore[arg-type]
            confidence=0.9, risk_if_wrong="low",
        )


def test_copied_with_evidence_constructs_and_roundtrips():
    c = GroundedClaim(
        label="copied", claim="exact quote", evidence_refs=["docs/plan.md#L4"],
        confidence=0.95, risk_if_wrong="low",
    )
    d = c.to_dict()
    assert d["label"] == "copied"
    assert d["evidence_refs"] == ["docs/plan.md#L4"]
    assert d["confidence"] == 0.95
