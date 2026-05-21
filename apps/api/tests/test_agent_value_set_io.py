"""Integration tests for the IO wrapper (PR 1 of #647).

These touch a real DB session (integration marker so they run on
the postgres+pgvector CI job, not the SQLite-shim unit job — same
discipline as the metacog_io tests from #617).

Locked behaviors:
  - Append-only: write_value_set always INSERTs a new row.
  - Latest-wins: read_value_set picks the most recent updated_at.
  - Version monotonic: each write bumps version.
  - kill-switch lookup is defensive (missing row → False).
  - The 5 shim callers all route through consult_with_audit and
    pass the right point + intent.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import Agent
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.services import agent_value_set_io as io
from app.services.agent_value_set import AgentValueSet

pytestmark = [pytest.mark.integration, pytest.mark.serial]


def _make_tenant_agent(db_session):
    """Insert a tenant + agent so the (tenant, agent) tuples below
    refer to real FK targets."""
    tenant = Tenant(name=f"value-layer-test-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.commit()
    agent = Agent(
        tenant_id=tenant.id,
        name="Luna",
    )
    db_session.add(agent)
    db_session.commit()
    return tenant, agent


# ── kill-switch ──────────────────────────────────────────────────────


def test_kill_switch_missing_features_row_defaults_false(db_session):
    """No tenant_features row → default OFF. The 5 consultation
    points see allow/kill_switch_off in this state."""
    tenant, _ = _make_tenant_agent(db_session)
    assert io.is_value_layer_enabled(db_session, tenant.id) is False


def test_kill_switch_flag_false_returns_false(db_session):
    tenant, _ = _make_tenant_agent(db_session)
    db_session.add(TenantFeatures(
        tenant_id=tenant.id,
        value_layer_enabled=False,
    ))
    db_session.commit()
    assert io.is_value_layer_enabled(db_session, tenant.id) is False


def test_kill_switch_flag_true_returns_true(db_session):
    tenant, _ = _make_tenant_agent(db_session)
    db_session.add(TenantFeatures(
        tenant_id=tenant.id,
        value_layer_enabled=True,
    ))
    db_session.commit()
    assert io.is_value_layer_enabled(db_session, tenant.id) is True


# ── read / write ──────────────────────────────────────────────────────


def test_read_empty_for_unseen_tenant_agent(db_session):
    """A (tenant, agent) with no value-set rows reads back
    AgentValueSet.empty(). Locked: every consult against this state
    returns allow/empty_value_set."""
    tenant, agent = _make_tenant_agent(db_session)
    vs = io.read_value_set(db_session, tenant_id=tenant.id, agent_id=agent.id)
    assert vs.is_empty()
    assert vs.version == 1


def test_write_then_read_round_trip(db_session):
    tenant, agent = _make_tenant_agent(db_session)
    result = io.write_value_set(
        db_session,
        tenant_id=tenant.id,
        agent_id=agent.id,
        protect=[{
            "slug": "production-main",
            "description": "production main branch",
            "added_at": "2026-05-21T00:00:00+00:00",
            "added_by": "operator",
        }],
        pursue=[],
        avoid=[],
    )
    assert result is not None
    assert result.version == 1

    read_back = io.read_value_set(
        db_session, tenant_id=tenant.id, agent_id=agent.id,
    )
    assert not read_back.is_empty()
    assert read_back.protect[0].slug == "production-main"
    assert read_back.version == 1


def test_write_is_append_only_with_monotonic_version(db_session):
    """Each write inserts a new row; version increments. Old rows
    stay in place (audit trail). Reads always pick the latest."""
    tenant, agent = _make_tenant_agent(db_session)

    io.write_value_set(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        protect=[{"slug": "v1-item", "description": "v1",
                  "added_at": "2026-05-21T00:00:00+00:00",
                  "added_by": "operator"}],
        pursue=[], avoid=[],
    )
    io.write_value_set(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        protect=[{"slug": "v2-item", "description": "v2",
                  "added_at": "2026-05-21T00:01:00+00:00",
                  "added_by": "operator"}],
        pursue=[], avoid=[],
    )

    latest = io.read_value_set(
        db_session, tenant_id=tenant.id, agent_id=agent.id,
    )
    # Latest wins: v2-item is what's surfaced
    assert latest.protect[0].slug == "v2-item"
    assert latest.version == 2

    # Both rows exist in agent_memories (append-only)
    from app.models.agent_memory import AgentMemory
    rows = (
        db_session.query(AgentMemory)
        .filter(
            AgentMemory.tenant_id == str(tenant.id),
            AgentMemory.agent_id == str(agent.id),
            AgentMemory.memory_type == io.VALUE_SET_MEMORY_TYPE,
        )
        .all()
    )
    assert len(rows) == 2


# ── consult_with_audit end-to-end ────────────────────────────────────


def test_consult_with_audit_returns_allow_when_kill_switch_off(db_session):
    """Defensive default: a tenant that hasn't opted in to the value
    layer sees allow/kill_switch_off even when their (hypothetical)
    value set has a protect item that would otherwise block."""
    tenant, agent = _make_tenant_agent(db_session)
    # Write a value set but DON'T flip the kill-switch
    io.write_value_set(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        protect=[{"slug": "production-main", "description": "prod",
                  "added_at": "x", "added_by": "operator"}],
        pursue=[], avoid=[],
    )

    verdict = io.consult_with_audit(
        db_session,
        tenant_id=tenant.id,
        agent_id=agent.id,
        action={"text": "deploy to production-main"},
        point="tool",
        intent="mutate",
    )
    assert verdict.decision == "allow"
    assert verdict.reason == "kill_switch_off"


def test_consult_with_audit_blocks_protect_mutation_when_enabled(db_session):
    tenant, agent = _make_tenant_agent(db_session)
    db_session.add(TenantFeatures(
        tenant_id=tenant.id,
        value_layer_enabled=True,
    ))
    db_session.commit()

    io.write_value_set(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        protect=[{"slug": "production-main", "description": "prod",
                  "added_at": "x", "added_by": "operator"}],
        pursue=[], avoid=[],
    )

    verdict = io.consult_with_audit(
        db_session,
        tenant_id=tenant.id,
        agent_id=agent.id,
        action={"text": "deploy to production-main"},
        point="tool",
        intent="mutate",
    )
    assert verdict.decision == "block"
    assert "protect_match" in verdict.reason
    assert verdict.matched_item["slug"] == "production-main"


# ── 5 shim callers ────────────────────────────────────────────────────


def _seed(db_session):
    tenant, agent = _make_tenant_agent(db_session)
    db_session.add(TenantFeatures(
        tenant_id=tenant.id, value_layer_enabled=True,
    ))
    db_session.commit()
    io.write_value_set(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        protect=[{"slug": "production-main", "description": "prod",
                  "added_at": "x", "added_by": "operator"}],
        pursue=[{"slug": "morning-report", "description": "habit",
                 "added_at": "x", "added_by": "operator"}],
        avoid=[{"slug": "force-push", "description": "no force pushes",
                "added_at": "x", "added_by": "operator"}],
    )
    return tenant, agent


def test_consult_routing_passes_correct_point_and_intent(db_session):
    tenant, agent = _seed(db_session)
    # Read intent
    v_read = io.consult_routing(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        intent_text="show production-main commits",
        intent_classifier_says_mutate=False,
    )
    assert v_read.consultation_point == "routing"
    assert v_read.decision == "warn"  # protect read → warn

    # Mutate intent
    v_mutate = io.consult_routing(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        intent_text="merge into production-main",
        intent_classifier_says_mutate=True,
    )
    assert v_mutate.decision == "block"


def test_consult_tool_carries_args_into_match(db_session):
    tenant, agent = _seed(db_session)
    v = io.consult_tool(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        tool_name="git_push",
        args={"branch": "production-main", "force": True},
        is_mutating=True,
    )
    assert v.consultation_point == "tool"
    assert v.decision == "block"
    # Both protect + avoid match here; protect wins on priority.
    assert v.matched_item["slug"] == "production-main"


def test_consult_reflection_intent_by_kind(db_session):
    tenant, agent = _seed(db_session)
    # 'risk' kind is descriptive → intent=read → warn (not block)
    v_descriptive = io.consult_reflection(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        reflection_kind="risk",
        reflection_content="Pattern: pushes to production-main fail at scale",
    )
    assert v_descriptive.decision == "warn"

    # 'next_move' kind proposes action → intent=mutate → block
    v_proposal = io.consult_reflection(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        reflection_kind="next_move",
        reflection_content="Push the hotfix to production-main tomorrow",
    )
    assert v_proposal.decision == "block"


def test_appraise_user_signal_with_values_surfaces_pursue_hit(db_session):
    """User-signal point passes intent=read by default. A pursue
    match returns allow with matched_item populated so the
    emotion_engine wrapper (Phase 1 PR 5) can scale PAD delta."""
    tenant, agent = _seed(db_session)
    v = io.appraise_user_signal_with_values(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        user_text="Where's the morning-report?",
    )
    assert v.decision == "allow"
    assert v.matched_item is not None
    assert v.matched_item["slug"] == "morning-report"


def test_synthesize_value_observations_proposal_intent(db_session):
    """Phase 2 hook: a value_proposal kind that itself touches a
    protected item must block — prevents self-referential
    contradictions."""
    tenant, agent = _seed(db_session)
    v = io.synthesize_value_observations(
        db_session,
        tenant_id=tenant.id, agent_id=agent.id,
        proposed_kind="value_proposal",
        proposed_content="Propose removing production-main from protect",
    )
    assert v.decision == "block"
    assert v.consultation_point == "synthesis"
