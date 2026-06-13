from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import workspaces as workspaces_route
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.agent import Agent
from app.models.agent_permission import AgentPermission
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.tenant_workspace import TenantWorkspaceAuditLog, TenantWorkspaceInstall
from app.models.user import User
from app.services.workspace_registry import install_workspace_pack

pytestmark = [pytest.mark.integration, pytest.mark.serial]


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def _tenant_with_user(db_session, *, superuser: bool = False):
    tenant = Tenant(name=f"workspace-test-{uuid.uuid4().hex[:8]}")
    db_session.add(tenant)
    db_session.commit()
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Workspace User",
        hashed_password="x",
        is_active=True,
        is_superuser=superuser,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    db_session.commit()
    return tenant, user


def _client(db_session, current_user) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[deps.get_db] = lambda: db_session
    app.dependency_overrides[deps.get_current_active_user] = lambda: current_user
    app.include_router(workspaces_route.router, prefix="/api/v1/workspaces")
    return TestClient(app, raise_server_exceptions=False)


def test_uninstalled_vet_pack_is_hidden_and_route_gated(db_session):
    _tenant, user = _tenant_with_user(db_session)
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    slugs = {w["slug"] for w in resp.json()["workspaces"]}
    assert "alpha-control" in slugs
    assert "vet-practice" not in slugs

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 404, resp.text


def test_installed_vet_pack_returns_widget_payload_envelopes(db_session):
    tenant, user = _tenant_with_user(db_session)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        display_order=10,
        reason="test install",
    )
    db_session.commit()
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    vet = next(w for w in resp.json()["workspaces"] if w["slug"] == "vet-practice")
    assert vet["route"] == "/workspaces/vet-practice"
    assert vet["summary"]["state"] == "setup_required"

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["descriptor"]["slug"] == "vet-practice"
    payloads = {w["key"]: w for w in body["widgets"]}
    assert {"launch_brief", "daily_work_queue", "system_readiness"}.issubset(payloads)
    assert payloads["launch_brief"]["example"] is True
    assert payloads["daily_work_queue"]["state"] in {"ready", "setup_required"}
    assert payloads["system_readiness"]["setup_blockers"]


def test_vet_pack_uses_installed_manifest_variant(db_session):
    tenant, user = _tenant_with_user(db_session)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        config={"fleet_variant": "cardiology_v1"},
        reason="cardiology install",
    )
    db_session.commit()
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 200, resp.text
    readiness = resp.json()["descriptor"]["summary"]["readiness"]
    assert readiness["agents_expected"] == 5
    assert readiness["workflows_expected"] == 1


def test_vet_pack_source_packets_use_install_config(db_session, monkeypatch):
    tenant, user = _tenant_with_user(db_session)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        config={
            "fleet_variant": "cardiology_v1",
            "source_packets": [
                {
                    "key": "brett",
                    "label": "Brett",
                    "provider": "google_drive",
                    "folder_id": "folder-123",
                }
            ],
        },
        reason="source packet test",
    )
    db_session.commit()

    def _fake_packet(db, tenant_id, *, folder_id, label, account_email=None, max_children=25):
        assert tenant_id == tenant.id
        assert folder_id == "folder-123"
        return {
            "label": label,
            "provider": "google_drive",
            "folder_id": folder_id,
            "folder_name": "Brett",
            "state": "ready",
            "counts": {"files": 4, "pdfs": 4, "folders": 0},
            "files": [{"id": "f1", "name": "Winnie Nieto.pdf", "kind": "pdf"}],
        }

    monkeypatch.setattr(
        "app.services.workspace_registry.list_google_drive_packet",
        _fake_packet,
    )
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 200, resp.text
    payloads = {w["key"]: w for w in resp.json()["widgets"]}
    assert payloads["source_packets"]["state"] == "ready"
    source = payloads["source_packets"]["data"]["sources"][0]
    assert source["folder_name"] == "Brett"
    assert source["files"][0]["name"] == "Winnie Nieto.pdf"


def test_feature_flag_can_hide_installed_pack(db_session):
    tenant, user = _tenant_with_user(db_session)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        reason="feature gate test",
    )
    features = (
        db_session.query(TenantFeatures)
        .filter(TenantFeatures.tenant_id == tenant.id)
        .one()
    )
    features.native_workspace_packs = False
    db_session.commit()
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    assert "vet-practice" not in {w["slug"] for w in resp.json()["workspaces"]}

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 404, resp.text


def test_workspace_detail_requires_installer_or_agent_permission(db_session):
    tenant, installer = _tenant_with_user(db_session)
    viewer = User(
        email=f"viewer-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Workspace Viewer",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        tenant_id=tenant.id,
    )
    db_session.add(viewer)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=installer.id,
        config={"fleet_variant": "gp_full"},
        reason="rbac test",
    )
    db_session.commit()

    viewer_client = _client(db_session, viewer)
    resp = viewer_client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 404, resp.text

    agent = Agent(
        tenant_id=tenant.id,
        name="Luna Supervisor",
        role="supervisor",
        status="production",
        tool_groups=[],
    )
    db_session.add(agent)
    db_session.flush()
    db_session.add(
        AgentPermission(
            agent_id=agent.id,
            tenant_id=tenant.id,
            principal_type="user",
            principal_id=viewer.id,
            permission="admin",
            granted_by=installer.id,
        )
    )
    db_session.commit()

    resp = viewer_client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 200, resp.text


def test_disabled_pack_is_not_visible_or_directly_accessible(db_session):
    tenant, user = _tenant_with_user(db_session)
    install = install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        status="disabled",
        reason="test disabled",
    )
    db_session.commit()
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    assert "vet-practice" not in {w["slug"] for w in resp.json()["workspaces"]}

    resp = client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 404, resp.text
    assert install.disabled_at is not None


def test_workspace_install_is_tenant_scoped(db_session):
    tenant, user = _tenant_with_user(db_session)
    other_tenant, other_user = _tenant_with_user(db_session)
    install_workspace_pack(
        db_session,
        tenant.id,
        "vet-practice",
        actor_user_id=user.id,
        display_order=10,
        reason="tenant scoped test",
    )
    db_session.commit()

    other_client = _client(db_session, other_user)
    resp = other_client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    assert "vet-practice" not in {w["slug"] for w in resp.json()["workspaces"]}

    resp = other_client.get("/api/v1/workspaces/vet-practice")
    assert resp.status_code == 404, resp.text
    assert (
        db_session.query(TenantWorkspaceInstall)
        .filter(TenantWorkspaceInstall.tenant_id == other_tenant.id)
        .count()
        == 0
    )


def test_catalog_includes_non_vet_pack_stub(db_session):
    _tenant, user = _tenant_with_user(db_session, superuser=True)
    client = _client(db_session, user)

    resp = client.get("/api/v1/workspaces/catalog")
    assert resp.status_code == 200, resp.text
    packs = {p["slug"]: p for p in resp.json()["packs"]}
    assert "vet-practice" in packs
    assert "sales-crm" in packs
    assert packs["sales-crm"]["category"] == "sales"
    assert packs["sales-crm"]["can_install"] is True


def test_superuser_install_writes_audit(db_session):
    tenant, user = _tenant_with_user(db_session, superuser=True)
    client = _client(db_session, user)

    resp = client.post(
        "/api/v1/workspaces/vet-practice/install",
        json={"display_order": 12, "reason": "operator install"},
    )
    assert resp.status_code == 200, resp.text
    install = (
        db_session.query(TenantWorkspaceInstall)
        .filter(
            TenantWorkspaceInstall.tenant_id == tenant.id,
            TenantWorkspaceInstall.workspace_slug == "vet-practice",
        )
        .one()
    )
    assert install.status == "enabled"
    audit = (
        db_session.query(TenantWorkspaceAuditLog)
        .filter(TenantWorkspaceAuditLog.install_id == install.id)
        .one()
    )
    assert audit.event_type == "install"
