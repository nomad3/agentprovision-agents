"""PR1 — Accountable Learning & Commitment System: typed contracts.

Pure, no-DB tests for the trace primitives and the extended commitment-state
vocabulary. Validates required fields and invalid-status rejection (plan §13
PR1 acceptance criteria).
"""
import dataclasses

import pytest

from app.schemas.accountable_learning import (
    LearningArtifact,
    OutcomeContract,
    RED_FLAG_LEVELS,
    MEMORY_CATEGORIES,
    red_flag_at_least,
)
from app.schemas.commitment_record import CommitmentState


def _contract(**over):
    base = dict(
        tenant_id="t1",
        contract_id="c1",
        session_id="s1",
        created_by_agent_id="luna",
        requester_ref="user:simon",
        goal="Merge PR #999",
        expected_outcome="PR #999 merged to main with green CI",
        definition_of_done=["PR merged", "CI green"],
        proof_required=["merged_pr_url", "ci_run_id"],
        owner_refs=["agent:luna"],
        risk_threshold="medium",
        escalation_policy="ask_user",
        status="proposed",
        created_at="2026-06-08T00:00:00Z",
        updated_at="2026-06-08T00:00:00Z",
    )
    base.update(over)
    return OutcomeContract(**base)


def _artifact(**over):
    base = dict(
        tenant_id="t1",
        artifact_id="a1",
        source_refs=["commitment:x"],
        task_summary="Scheduled a follow-up that slipped",
        intended_outcome="Follow-up sent by Friday",
        observed_outcome="Follow-up missed; no proof",
        outcome_quality="failed",
        proof_refs=[],
        failed_assumptions=["assumed calendar invite implied confirmation"],
        user_corrections=["user clarified the deadline was hard"],
        memory_write_recommendation="failed_assumption",
        confidence="high",
        created_at="2026-06-08T00:00:00Z",
    )
    base.update(over)
    return LearningArtifact(**base)


# ── OutcomeContract ───────────────────────────────────────────────────

def test_outcome_contract_valid_construction():
    c = _contract()
    assert c.goal == "Merge PR #999"
    assert c.definition_of_done == ["PR merged", "CI green"]


def test_outcome_contract_is_frozen():
    c = _contract()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.status = "active"  # type: ignore[misc]


def test_outcome_contract_requires_tenant():
    with pytest.raises(ValueError, match="tenant_id"):
        _contract(tenant_id="")


def test_outcome_contract_requires_done_definition():
    with pytest.raises(ValueError, match="definition_of_done"):
        _contract(definition_of_done=[])


def test_outcome_contract_requires_owner():
    with pytest.raises(ValueError, match="owner_refs"):
        _contract(owner_refs=[])


def test_outcome_contract_rejects_bad_status():
    with pytest.raises(ValueError, match="status"):
        _contract(status="totally_made_up")


def test_outcome_contract_rejects_bad_risk_threshold():
    with pytest.raises(ValueError, match="risk_threshold"):
        _contract(risk_threshold="catastrophic")


def test_outcome_contract_rejects_bad_escalation_policy():
    with pytest.raises(ValueError, match="escalation_policy"):
        _contract(escalation_policy="page_everyone")


# ── LearningArtifact ──────────────────────────────────────────────────

def test_learning_artifact_valid_construction():
    a = _artifact()
    assert a.outcome_quality == "failed"
    assert a.memory_write_recommendation == "failed_assumption"


def test_learning_artifact_rejects_bad_quality():
    with pytest.raises(ValueError, match="outcome_quality"):
        _artifact(outcome_quality="kinda_ok")


def test_learning_artifact_rejects_bad_memory_category():
    with pytest.raises(ValueError, match="memory_write_recommendation"):
        _artifact(memory_write_recommendation="vibes")


def test_learning_artifact_allows_none_memory_recommendation():
    a = _artifact(memory_write_recommendation="none")
    assert a.memory_write_recommendation == "none"


def test_learning_artifact_requires_summary():
    with pytest.raises(ValueError, match="task_summary"):
        _artifact(task_summary="")


# ── Red-flag ordering ─────────────────────────────────────────────────

def test_red_flag_levels_locked():
    assert RED_FLAG_LEVELS == {"watch", "warn", "escalate", "block"}


def test_red_flag_at_least_ordering():
    assert red_flag_at_least("block", "warn") is True
    assert red_flag_at_least("warn", "warn") is True
    assert red_flag_at_least("watch", "warn") is False


def test_red_flag_at_least_rejects_unknown():
    with pytest.raises(ValueError):
        red_flag_at_least("meltdown", "warn")


# ── Extended commitment-state vocabulary (reconciled, not forked) ──────

def test_commitment_state_keeps_canonical_values():
    # The existing canonical states must remain (no silent rename to the plan's
    # done/failed/canceled spelling).
    values = {s.value for s in CommitmentState}
    assert {"open", "in_progress", "fulfilled", "broken", "cancelled"} <= values


def test_commitment_state_adds_plan_states():
    values = {s.value for s in CommitmentState}
    assert {"blocked", "at_risk", "renegotiated"} <= values


def test_memory_categories_cover_plan_table():
    assert {
        "fact",
        "preference",
        "commitment",
        "pattern",
        "failed_assumption",
        "business_context",
        "emotional_context",
        "stale_context",
    } <= MEMORY_CATEGORIES
