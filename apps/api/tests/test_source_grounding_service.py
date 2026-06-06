"""Tests for PR 2 source-grounding service helpers (user-facing safety)."""
from app.schemas.source_grounding import GroundedClaim
from app.services.source_grounding import (
    is_source_backed,
    requires_user_facing_caveat,
    user_facing_caveat,
    render_claim_for_user,
    summarize_grounding,
)


def test_source_backed_labels():
    assert is_source_backed("copied") is True
    assert is_source_backed("adapted") is True
    assert is_source_backed("inferred") is False
    assert is_source_backed("speculative") is False


def test_caveat_required_for_non_source_backed_only():
    assert requires_user_facing_caveat("speculative") is True
    assert requires_user_facing_caveat("inferred") is True
    assert requires_user_facing_caveat("copied") is False
    assert requires_user_facing_caveat("adapted") is False


def test_user_facing_caveat_names_the_label():
    assert user_facing_caveat("copied") == ""
    assert user_facing_caveat("adapted") == ""
    assert "speculative" in user_facing_caveat("speculative").lower()
    assert "inferred" in user_facing_caveat("inferred").lower()


def test_render_prefixes_caveat_for_speculation_but_not_source_backed():
    spec = GroundedClaim("speculative", "we could try X", [], 0.3, "medium")
    out = render_claim_for_user(spec)
    assert "we could try X" in out
    assert out != "we could try X"  # a caveat was prepended

    copied = GroundedClaim("copied", "exact quote", ["s"], 0.95, "low")
    assert render_claim_for_user(copied) == "exact quote"


def test_summarize_reports_weakest_link_and_speculation():
    claims = [
        GroundedClaim("copied", "a", ["s"], 0.95, "low"),
        GroundedClaim("speculative", "b", [], 0.3, "high"),
        GroundedClaim("inferred", "c", [], 0.6, "medium"),
    ]
    s = summarize_grounding(claims)
    assert s["min_confidence"] == 0.3
    assert s["max_risk_if_wrong"] == "high"
    assert s["has_speculative"] is True
    assert s["counts"]["speculative"] == 1
    assert s["counts"]["copied"] == 1


def test_summarize_empty_is_safe():
    s = summarize_grounding([])
    assert s["has_speculative"] is False
    assert s["min_confidence"] is None
    assert s["max_risk_if_wrong"] is None
