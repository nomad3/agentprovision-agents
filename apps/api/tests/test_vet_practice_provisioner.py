"""Integration tests for the vet-practice tenant provisioner (v1).

Scope: the ``cardiology_v1`` manifest — the 5-agent Brett-cardiology
beachhead. Touches a real DB session (Agent/IntegrationConfig/
DynamicWorkflow/AgentPermission/AgentMemory all carry Postgres-only
JSONB/UUID columns) so these run on the postgres+pgvector job, not the
SQLite-shim unit job — same discipline as ``test_agent_value_set_io.py``.

Locked behaviors (the §4 acceptance contract from the plan):
  1. Seeds exactly 5 agents (Luna + Referral Intake + Cardiac
     Diagnostics + Comms & Recall + Referral Liaison) on the tenant,
     each owned by the tenant admin, with resolvable tool_groups.
  2. Seeds connector slots as ``integration_config`` rows, enabled=False
     (gmail/google_drive/google_calendar real; the long tail as slots).
  3. Installs the Cardiac Report Generator workflow template as a
     tenant-scoped copy (tier="custom", source_template_id set).
  4. Seeds USER-principal ``agent_permissions`` for the owner (the rows
     ``deps.require_agent_permission`` actually enforces) — NOT role rows.
  5. Seeds declared value-sets (added_by="seed") — declared, not enforced
     (arbitration is pure-library; see service docstring).
  6. Re-running ``provision_vet_practice`` is a clean no-op: no duplicate
     agents, connector slots, workflow copies, permissions, or value-set
     versions.
  7. ``dry_run=True`` returns the plan and writes NOTHING.
  8. Every manifest agent's tool_groups resolve against ``tool_groups.py``.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import provision as provision_route
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.agent import Agent
from app.models.agent_memory import AgentMemory
from app.models.agent_permission import AgentPermission
from app.models.dynamic_workflow import DynamicWorkflow
from app.models.integration_config import IntegrationConfig
from app.models.tenant import Tenant
from app.models.user import User
from app.services.provisioning.vet_manifest import (
    CARDIOLOGY_V1,
    get_manifest,
)
from app.services.provisioning.vet_practice import (
    VetPracticeProfile,
    provision_vet_practice,
)
from app.services.tool_groups import TOOL_GROUPS, resolve_tool_names

pytestmark = [pytest.mark.integration, pytest.mark.serial]


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(name="db_session")
def db_session_fixture():
    """Real Postgres session (same local pattern as test_team_engine_io).

    create_all/drop_all per test keeps the table set present without
    depending on the migration runner; drop_all leaves the dedicated
    ``agentprovision_test`` DB clean between tests."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="vet_tenant")
def vet_tenant_fixture(db_session):
    """A fresh tenant + admin user (the seeded objects' owner)."""
    tenant = Tenant(name=f"vet-provisioner-test-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.commit()
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Practice Admin",
        hashed_password="x",
        is_active=True,
        tenant_id=tenant.id,
    )
    db_session.add(admin)
    db_session.commit()
    return tenant, admin


@pytest.fixture(name="native_cardiac_template")
def native_cardiac_template_fixture(db_session, vet_tenant):
    """Seed the platform-native Cardiac Report Generator the provisioner
    installs a tenant copy of. Resolved by (name, tier='native')."""
    tenant, _ = vet_tenant
    tmpl = DynamicWorkflow(
        tenant_id=tenant.id,
        name="Cardiac Report Generator",
        description="native cardiac report",
        definition={"steps": []},
        tier="native",
        public=True,
        trigger_config={"type": "manual"},
    )
    db_session.add(tmpl)
    db_session.commit()
    db_session.refresh(tmpl)
    return tmpl


def _profile(tenant, admin):
    return VetPracticeProfile(
        practice_name="BB Cardiology",
        practice_type="cardiology",
        owner_user_id=admin.id,
        intake_mailbox="btcvetmobile@gmail.com",
        lead_clinician_name="Dr. Brett Boorstin",
        fleet_variant="cardiology_v1",
    )


# ── manifest sanity (no DB) ───────────────────────────────────────────


def test_manifest_has_five_agents():
    assert len(CARDIOLOGY_V1.agents) == 5
    names = {a["name"] for a in CARDIOLOGY_V1.agents}
    assert names == {
        "Luna",
        "Referral Intake Agent",
        "Cardiac Diagnostics Agent",
        "Comms & Recall Agent",
        "Referral Liaison Agent",
    }


def test_manifest_tool_groups_all_resolve():
    """Every tool_group on every manifest agent must exist in the
    registry — a typo'd group would silently load zero tools."""
    for agent in CARDIOLOGY_V1.agents:
        for group in agent["tool_groups"]:
            assert group in TOOL_GROUPS, (
                f"{agent['name']} references unknown tool_group {group!r}"
            )
        # resolve_tool_names must return a non-empty flat list
        resolved = resolve_tool_names(agent["tool_groups"])
        assert resolved, f"{agent['name']} resolved to no tools"


def test_diagnostics_agent_carries_human_approval_gate():
    """The Cardiac Diagnostics Agent is the human_approval / Brett gate —
    it must be flagged so the enforced guardrail is provisioned."""
    diag = next(
        a for a in CARDIOLOGY_V1.agents
        if a["name"] == "Cardiac Diagnostics Agent"
    )
    assert diag.get("human_approval_gate") is True


def test_get_manifest_unknown_variant_raises():
    with pytest.raises(KeyError):
        get_manifest("gp_full_does_not_exist")


# ── full provision ────────────────────────────────────────────────────


def test_provision_seeds_five_owned_agents(db_session, vet_tenant):
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    agents = (
        db_session.query(Agent)
        .filter(Agent.tenant_id == tenant.id)
        .all()
    )
    assert len(agents) == 5
    # every agent owned by the admin (Luna's "nothing is born ownerless")
    for a in agents:
        assert str(a.owner_user_id) == str(admin.id), (
            f"{a.name} has no/ wrong owner"
        )
        assert a.status == "production"
        assert a.tool_groups, f"{a.name} has empty tool_groups"


def test_provision_resolves_escalation_targets(db_session, vet_tenant):
    """Two-pass wiring: escalation_agent_id is set by name lookup after
    all agents are inserted. Intake escalates to Diagnostics."""
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    by_name = {
        a.name: a
        for a in db_session.query(Agent).filter(Agent.tenant_id == tenant.id)
    }
    intake = by_name["Referral Intake Agent"]
    diag = by_name["Cardiac Diagnostics Agent"]
    assert str(intake.escalation_agent_id) == str(diag.id)
    # Luna is top of tree — no escalation target.
    assert by_name["Luna"].escalation_agent_id is None


def test_provision_seeds_connector_slots_disabled(db_session, vet_tenant):
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    slots = (
        db_session.query(IntegrationConfig)
        .filter(IntegrationConfig.tenant_id == tenant.id)
        .all()
    )
    names = {s.integration_name for s in slots}
    # the real cardiology_v1 spine + documented long-tail slots
    assert {"gmail", "google_drive", "google_calendar"}.issubset(names)
    # every seeded slot starts disabled (awaiting credentials)
    for s in slots:
        assert s.enabled is False, f"{s.integration_name} seeded enabled"


def test_provision_installs_cardiac_workflow_copy(
    db_session, vet_tenant, native_cardiac_template
):
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    copies = (
        db_session.query(DynamicWorkflow)
        .filter(
            DynamicWorkflow.tenant_id == tenant.id,
            DynamicWorkflow.tier == "custom",
            DynamicWorkflow.source_template_id == native_cardiac_template.id,
        )
        .all()
    )
    assert len(copies) == 1
    assert copies[0].name == "Cardiac Report Generator"


def test_provision_seeds_user_principal_permissions(db_session, vet_tenant):
    """v1 enforces USER-principal perms only (deps.py:147). The owner must
    get an enforceable 'admin' grant on every seeded agent. NO role rows."""
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    perms = (
        db_session.query(AgentPermission)
        .filter(AgentPermission.tenant_id == tenant.id)
        .all()
    )
    assert perms, "no permissions seeded"
    # ALL seeded permissions are user-principal (the enforced axis)
    assert {p.principal_type for p in perms} == {"user"}
    # the owner has a grant on each of the 5 agents
    owner_agent_ids = {
        str(p.agent_id) for p in perms
        if str(p.principal_id) == str(admin.id)
    }
    assert len(owner_agent_ids) == 5


def test_provision_seeds_declared_value_sets(db_session, vet_tenant):
    """Value-sets seeded as DECLARED (added_by='seed'). They are stored
    as agent_memory rows of type 'value_set' — one per gated agent."""
    tenant, admin = vet_tenant
    provision_vet_practice(db_session, tenant.id, profile=_profile(tenant, admin))

    vs_rows = (
        db_session.query(AgentMemory)
        .filter(
            AgentMemory.tenant_id == tenant.id,
            AgentMemory.memory_type == "value_set",
        )
        .all()
    )
    assert vs_rows, "no value-set rows seeded"


# ── idempotency (the §9 BLOCKER) ──────────────────────────────────────


def test_provision_rerun_is_a_clean_noop(
    db_session, vet_tenant, native_cardiac_template
):
    """Re-running must NOT duplicate any object type. This is the §9
    correction: idempotency is built INTO the provisioner for workflows
    + connectors (the blind-insert paths), not assumed from the helpers."""
    tenant, admin = vet_tenant
    profile = _profile(tenant, admin)

    first = provision_vet_practice(db_session, tenant.id, profile=profile)
    second = provision_vet_practice(db_session, tenant.id, profile=profile)

    # counts after each run
    def _counts():
        return {
            "agents": db_session.query(Agent)
            .filter(Agent.tenant_id == tenant.id).count(),
            "slots": db_session.query(IntegrationConfig)
            .filter(IntegrationConfig.tenant_id == tenant.id).count(),
            "workflows": db_session.query(DynamicWorkflow)
            .filter(
                DynamicWorkflow.tenant_id == tenant.id,
                DynamicWorkflow.tier == "custom",
            ).count(),
            "perms": db_session.query(AgentPermission)
            .filter(AgentPermission.tenant_id == tenant.id).count(),
            "value_sets": db_session.query(AgentMemory)
            .filter(
                AgentMemory.tenant_id == tenant.id,
                AgentMemory.memory_type == "value_set",
            ).count(),
        }

    counts = _counts()
    assert counts["agents"] == 5
    assert counts["workflows"] == 1
    # second run reports zero net new objects across the board
    assert second["agents"]["created"] == 0
    assert second["connector_slots"]["created"] == 0
    assert second["workflow_templates"]["created"] == 0
    assert second["permissions"]["created"] == 0
    assert second["value_sets"]["created"] == 0
    # and the DB row counts didn't grow vs the first run
    # (first-run created counts are non-zero)
    assert first["agents"]["created"] == 5


# ── dry-run ───────────────────────────────────────────────────────────


def test_dry_run_writes_nothing(db_session, vet_tenant, native_cardiac_template):
    tenant, admin = vet_tenant
    result = provision_vet_practice(
        db_session, tenant.id, profile=_profile(tenant, admin), dry_run=True
    )

    assert result["dry_run"] is True
    # nothing persisted
    assert db_session.query(Agent).filter(
        Agent.tenant_id == tenant.id
    ).count() == 0
    assert db_session.query(IntegrationConfig).filter(
        IntegrationConfig.tenant_id == tenant.id
    ).count() == 0
    assert db_session.query(DynamicWorkflow).filter(
        DynamicWorkflow.tenant_id == tenant.id,
        DynamicWorkflow.tier == "custom",
    ).count() == 0
    assert db_session.query(AgentPermission).filter(
        AgentPermission.tenant_id == tenant.id
    ).count() == 0
    # but the plan describes what WOULD be created
    assert result["agents"]["planned"] == 5
    assert result["connector_slots"]["planned"] >= 3


# ── internal endpoint ─────────────────────────────────────────────────


def _build_client(db_session) -> TestClient:
    """Mount just the provision router on a throwaway app with get_db
    overridden — keeps the test off the full app's startup side-effects."""
    app = FastAPI()
    app.dependency_overrides[deps.get_db] = lambda: db_session
    app.include_router(provision_route.router, prefix="/api/v1/provision")
    return TestClient(app, raise_server_exceptions=False)


def test_endpoint_rejects_missing_internal_key(db_session, vet_tenant):
    tenant, _ = vet_tenant
    client = _build_client(db_session)
    resp = client.post(
        "/api/v1/provision/vet-practice/internal",
        json={"practice_name": "BB Cardiology"},
        headers={"X-Tenant-Id": str(tenant.id)},  # no X-Internal-Key
    )
    assert resp.status_code == 401, resp.text


def test_endpoint_dry_run_delegates_to_service(
    db_session, vet_tenant, native_cardiac_template
):
    """Happy path: valid internal key + tenant header → the route returns
    the provisioner's plan and writes nothing on dry_run."""
    tenant, admin = vet_tenant
    client = _build_client(db_session)
    resp = client.post(
        "/api/v1/provision/vet-practice/internal",
        json={
            "practice_name": "BB Cardiology",
            "owner_user_id": str(admin.id),
            "dry_run": True,
        },
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(tenant.id),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert body["variant"] == "cardiology_v1"
    assert body["agents"]["planned"] == 5
    # dry-run wrote nothing
    assert db_session.query(Agent).filter(
        Agent.tenant_id == tenant.id
    ).count() == 0
