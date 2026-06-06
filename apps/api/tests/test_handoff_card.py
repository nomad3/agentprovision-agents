"""Tests for PR 3 — team handoff cards (trusted-teammate engines)."""
import pytest

from app.schemas.handoff_card import HandoffCard


def _valid(**overrides):
    base = dict(
        tenant_id="t1",
        from_agent="luna",
        to_agent="claudia",
        objective="Add source-grounding labels",
        system="agentprovision-agents",
        source_docs=["docs/plans/2026-06-04-trusted-teammate-engines.md"],
        constraints=["trace-only", "no hot-path wiring"],
        non_goals=["do not block actions"],
        expected_artifact="PR with schema + service + tests",
        reviewer_focus=["evidence-before-interpretation invariant"],
        stop_conditions=["tests fail", "scope grows beyond the schema"],
        created_at="2026-06-06T05:00:00Z",
    )
    base.update(overrides)
    return HandoffCard(**base)


def test_valid_card_constructs_and_roundtrips():
    c = _valid()
    d = c.to_dict()
    assert d["from_agent"] == "luna"
    assert d["to_agent"] == "claudia"
    assert d["reviewer_focus"] == ["evidence-before-interpretation invariant"]


def test_stop_conditions_required_non_empty():
    # A handoff with no stop conditions lets the receiver run past its mandate.
    with pytest.raises(ValueError):
        _valid(stop_conditions=[])


def test_reviewer_focus_required_non_empty():
    # The card is the review contract; it must say what to scrutinise.
    with pytest.raises(ValueError):
        _valid(reviewer_focus=[])


def test_objective_required():
    with pytest.raises(ValueError):
        _valid(objective="   ")


def test_system_required():
    with pytest.raises(ValueError):
        _valid(system="")


def test_expected_artifact_required():
    with pytest.raises(ValueError):
        _valid(expected_artifact="")


def test_handoff_must_cross_between_two_agents():
    # Handing a task to yourself is not a handoff.
    with pytest.raises(ValueError):
        _valid(from_agent="luna", to_agent="luna")


def test_tenant_id_required():
    with pytest.raises(ValueError):
        _valid(tenant_id="")


def test_list_fields_must_be_lists():
    with pytest.raises(ValueError):
        _valid(constraints="trace-only")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _valid(source_docs="docs/x.md")  # type: ignore[arg-type]
