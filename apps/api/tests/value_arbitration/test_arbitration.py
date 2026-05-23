"""Unit tests for the pure ValueArbitration library.

Covers the eight scenarios from design §7.1 plus the
``substrate_integrity`` throttled-outcome check (per Luna review §9
resolution).

This file MUST NOT import any live decision-path module
(``agent_router``, ``cli_session_manager``, etc.) — per design §0
Hard Gate, the arbitrator is design-only until P0a + P0c land.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.services import value_arbitration as va
from app.services.value_arbitration import (
    ArbitrationOutcome,
    Candidate,
    DecisionContext,
    Direction,
    MissingProvenance,
    SourceClass,
    Standing,
    TrustWeights,
    ValueSignal,
    ValueTarget,
    arbitrate,
    standing_bounds,
    validate_signal,
)

from .fixtures import (
    AGENT_ID,
    NOW,
    TENANT_ID,
    _ctx,
    _sig,
    scenario_avoid,
    scenario_missing_provenance,
    scenario_pursue,
    scenario_tenant_veto,
    scenario_tie,
)


# ── §7.1 #1: Provenance rejection across every source class ──────────


@pytest.mark.parametrize("source", list(SourceClass))
def test_provenance_rejection_missing_confidence(source):
    """Every source class rejects a signal with missing confidence."""
    sig = ValueSignal(
        source=source,
        source_id="x",
        timestamp=NOW,
        tenant_id=TENANT_ID,
        # agent_id is optional only for safety_floor / tenant_norm; supply it
        # universally so this test isolates the confidence-None breach.
        agent_id=AGENT_ID,
        confidence=None,
        standing=Standing.advisory,
        direction=Direction.pursue,
        target=ValueTarget(kind="tool_call", ref="t"),
    )
    with pytest.raises(MissingProvenance):
        validate_signal(sig)


def test_provenance_rejection_missing_agent_id_for_agent_scoped_source():
    """``agent_id=None`` is rejected unless source is safety_floor / tenant_norm."""
    sig = ValueSignal(
        source=SourceClass.peer_agent,
        source_id="p",
        timestamp=NOW,
        tenant_id=TENANT_ID,
        agent_id=None,
        confidence=0.5,
        standing=Standing.advisory,
        direction=Direction.pursue,
        target=ValueTarget(kind="tool_call", ref="t"),
    )
    with pytest.raises(MissingProvenance):
        validate_signal(sig)


def test_provenance_allows_null_agent_id_for_safety_floor_and_tenant_norm():
    for source in (SourceClass.safety_floor, SourceClass.tenant_norm):
        sig = ValueSignal(
            source=source,
            source_id="s",
            timestamp=NOW,
            tenant_id=TENANT_ID,
            agent_id=None,
            confidence=0.9,
            standing=Standing.veto_bearing,
            direction=Direction.veto,
            target=ValueTarget(kind="tool_call", ref="t"),
        )
        assert validate_signal(sig) is True


# ── §7.1 #2: Constitutional (absolute) veto blocks everything ─────────


def test_absolute_veto_blocks_even_against_strong_pursue_majority():
    context = _ctx()
    # 10 strong-pursue signals can't override a single absolute veto.
    pursues = [
        _sig(
            source=SourceClass.operator_intent,
            standing=Standing.strong_advisory,
            direction=Direction.pursue,
            confidence=1.0,
            source_id=f"op-{i}",
        )
        for i in range(10)
    ]
    absolute_veto = _sig(
        source=SourceClass.safety_floor,
        standing=Standing.absolute,
        direction=Direction.veto,
        confidence=1.0,
        source_id="safety-abs-1",
        agent_id=None,
    )
    weights = TrustWeights(default=2.0)
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, pursues + [absolute_veto], weights, candidates)
    assert result.outcome == ArbitrationOutcome.blocked
    assert result.reason == "absolute_veto"


# ── §7.1 #3: Veto-bearing — DISJUNCTIVE per Luna correction ───────────


def test_veto_bearing_is_disjunctive_single_veto_blocks():
    """Any single veto-bearing veto blocks; unanimity is NOT required."""
    context = _ctx()
    veto = _sig(
        source=SourceClass.tenant_norm,
        standing=Standing.veto_bearing,
        direction=Direction.veto,
        confidence=1.0,
        source_id="norm-1",
        agent_id=None,
    )
    abstainer = _sig(
        # A second veto-bearing source that does NOT veto (here it pursues).
        # Earlier-draft unanimity rule would have let this rescue the action;
        # disjunctive rule does not.
        source=SourceClass.tenant_norm,
        standing=Standing.veto_bearing,
        direction=Direction.pursue,
        confidence=1.0,
        source_id="norm-2",
        agent_id=None,
    )
    weights = TrustWeights(default=1.0)
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, [veto, abstainer], weights, candidates)
    assert result.outcome == ArbitrationOutcome.blocked
    assert result.reason == "veto_bearing_block"


def test_veto_bearing_class_with_no_vetoes_enters_weighted_sum():
    """If no veto-bearing signal has direction=veto, they enter scoring."""
    context = _ctx()
    pursue_norm = _sig(
        source=SourceClass.tenant_norm,
        standing=Standing.veto_bearing,
        direction=Direction.pursue,
        confidence=1.0,
        source_id="norm-1",
        agent_id=None,
    )
    weights = TrustWeights(default=1.0)
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, [pursue_norm], weights, candidates)
    assert result.outcome == ArbitrationOutcome.preferred
    assert result.scores["tool_call:send_email"] > 0


# ── §7.1 #4: Standing-class weight clamps ─────────────────────────────


def test_standing_class_weight_clamp_advisory():
    """Advisory weight is clamped to [0.1, 1.0] at read time."""
    context = _ctx()
    sig = _sig(
        source=SourceClass.user_of_moment,
        standing=Standing.advisory,
        direction=Direction.pursue,
        confidence=1.0,
        source_id="u-1",
    )
    # weight 5.0 exceeds advisory max (1.0) and must clamp.
    weights = TrustWeights(
        weights={(TENANT_ID, SourceClass.user_of_moment, AGENT_ID): 5.0},
        default=1.0,
    )
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, [sig], weights, candidates)
    assert result.outcome == ArbitrationOutcome.preferred
    # exactly the clamped contribution: sign(+1) * applicability(1.0) * 1.0 * conf(1.0)
    assert result.scores["tool_call:send_email"] == pytest.approx(1.0)
    # trace records the clamp
    weighted_entries = [t for t in result.trace if t.rule == "weighted"]
    assert weighted_entries[0].weight_raw == 5.0
    assert weighted_entries[0].weight_clamped == 1.0


def test_standing_bounds_returns_expected_ranges():
    assert standing_bounds(Standing.absolute) == (1.0, 1.0)
    assert standing_bounds(Standing.veto_bearing) == (1.0, 1.0)
    assert standing_bounds(Standing.strong_advisory) == (0.5, 2.0)
    assert standing_bounds(Standing.advisory) == (0.1, 1.0)


# ── §7.1 #5: Tie within epsilon → abstain ─────────────────────────────


def test_tie_within_epsilon_abstains():
    context, signals, weights, candidates = scenario_tie()
    result = arbitrate(context, signals, weights, candidates, tie_epsilon=0.05)
    assert result.outcome == ArbitrationOutcome.abstain
    assert result.reason == "tie_within_epsilon"
    # Ordering still populated so caller can inspect even on abstain.
    assert len(result.ordering) == 2


# ── §7.1 #6: Trace completeness ───────────────────────────────────────


def test_trace_includes_admitted_and_rejected_signals():
    context, signals, weights, candidates = scenario_missing_provenance()
    result = arbitrate(context, signals, weights, candidates)
    # The bad signal becomes a rejected trace entry; the good signal becomes
    # a weighted entry.
    rejected = [t for t in result.trace if t.rule == "rejected"]
    weighted = [t for t in result.trace if t.rule == "weighted"]
    assert len(rejected) == 1
    assert "confidence" in rejected[0].rejected_reason
    assert len(weighted) == 1
    assert weighted[0].source == SourceClass.operator_intent
    # rejected list on the result also surfaces it for the audit IO wrapper.
    assert len(result.rejected) == 1


# ── §7.1 #7: Audit fail-closed (caller responsibility) ───────────────


def test_missing_provenance_propagates_at_explicit_validate_call():
    """``validate_signal`` MUST raise — callers cannot rely on silent skip.

    Per §4.2: the exception is the structural enforcement. The arbitrator
    builds a rejected-trace entry from it (verified in the previous test),
    but anything that explicitly calls ``validate_signal`` — including
    future IO wrappers — gets the exception.
    """
    bad = ValueSignal(
        source=SourceClass.peer_agent,
        source_id="p-1",
        timestamp=NOW,
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        confidence=None,
        standing=Standing.advisory,
        direction=Direction.pursue,
        target=ValueTarget(kind="tool_call", ref="t"),
    )
    with pytest.raises(MissingProvenance):
        validate_signal(bad)


# ── §7.1 #8: Reproducibility ──────────────────────────────────────────


def test_reproducibility_same_inputs_yield_same_result():
    context, signals, weights, candidates = scenario_avoid()
    r1 = arbitrate(context, signals, weights, candidates)
    r2 = arbitrate(context, signals, weights, candidates)
    assert r1.outcome == r2.outcome
    assert r1.scores == r2.scores
    assert r1.ordering == r2.ordering
    # Trace is the same shape; TraceEntry is frozen dataclass so equality holds.
    assert r1.trace == r2.trace


# ── §9 Luna resolution: substrate_integrity → throttled, NOT blocked ──


def test_substrate_integrity_veto_produces_throttled_not_blocked():
    """Substrate-integrity vetoes carry a distinct outcome (operational
    deferral, NOT moral refusal). Mixing them with ``blocked`` would
    train the value layer as if the action was forbidden, not deferred.
    """
    context = _ctx()
    rate_limit = _sig(
        source=SourceClass.substrate_integrity,
        standing=Standing.veto_bearing,
        direction=Direction.veto,
        confidence=1.0,
        source_id="rate-limit-1",
        rationale="executor saturation; back off 30s",
    )
    # Even with strong pursue signals around it, throttled wins.
    pursue = _sig(
        source=SourceClass.operator_intent,
        standing=Standing.strong_advisory,
        direction=Direction.pursue,
        confidence=1.0,
        source_id="op-1",
    )
    weights = TrustWeights(default=1.0)
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, [rate_limit, pursue], weights, candidates)
    assert result.outcome == ArbitrationOutcome.throttled
    assert result.reason == "substrate_integrity_throttle"
    # Critically NOT blocked — the distinction matters for downstream
    # learning (retry logic vs. value-layer negative-example training).
    assert result.outcome != ArbitrationOutcome.blocked


def test_substrate_throttle_takes_precedence_over_other_veto_bearing():
    """If both substrate and tenant_norm veto, substrate wins (throttled).

    Rationale: a substrate-saturated system can't reliably evaluate
    moral constraints either. Operationally deferring + retrying lets
    the moral evaluation happen with a stable substrate.
    """
    context = _ctx()
    substrate = _sig(
        source=SourceClass.substrate_integrity,
        standing=Standing.veto_bearing,
        direction=Direction.veto,
        confidence=1.0,
        source_id="rate-1",
    )
    tenant_veto = _sig(
        source=SourceClass.tenant_norm,
        standing=Standing.veto_bearing,
        direction=Direction.veto,
        confidence=1.0,
        source_id="norm-1",
        agent_id=None,
    )
    weights = TrustWeights(default=1.0)
    candidates = [Candidate(kind="tool_call", ref="send_email")]
    result = arbitrate(context, [substrate, tenant_veto], weights, candidates)
    assert result.outcome == ArbitrationOutcome.throttled


# ── Convenience smoke tests over the small scenarios ─────────────────


def test_scenario_pursue_prefers_the_single_candidate():
    context, signals, weights, candidates = scenario_pursue()
    result = arbitrate(context, signals, weights, candidates)
    assert result.outcome == ArbitrationOutcome.preferred
    assert result.ordering[0].ref == "send_email"


def test_scenario_avoid_blocks_pursued_candidate_via_negative_sum():
    context, signals, weights, candidates = scenario_avoid()
    result = arbitrate(context, signals, weights, candidates)
    assert result.outcome == ArbitrationOutcome.preferred
    # send_email should rank below archive because avoid signal dominates.
    assert result.ordering[0].ref == "archive"


def test_scenario_tenant_veto_blocks():
    context, signals, weights, candidates = scenario_tenant_veto()
    result = arbitrate(context, signals, weights, candidates)
    assert result.outcome == ArbitrationOutcome.blocked
    assert result.reason == "veto_bearing_block"
