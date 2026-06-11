"""Luna P5.4b — desktop_actuate tests (grant-gated agent act).

Covers `desktop_act.actuate_command` and the user-JWT + internal `/commands/actuate`
routes. The contract: an EXISTING active grant (minted by a human via P5.5) is
required to enqueue one bounded native command through the shared lifecycle. No
grant → `approval_required` (NO command). Wrong-owner/session/expired/revoked/
exhausted/not-native grant → structured deny (NO command). Per-capability flag is
default-off, so only a flag-enabled (operator-like) tenant reaches a queued
command. actuate NEVER mints a grant.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.desktop_control import router as desktop_control_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.chat import ChatSession
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import desktop_act

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222223")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER_SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333334")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
DEVICE_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
BUNDLE = "net.whatsapp.WhatsApp"

OTHER_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TENANT_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_READINESS_MISSING = object()


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _allowlist_floor(monkeypatch):
    monkeypatch.setattr(
        settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [BUNDLE], raising=False
    )


def _seed(db, *, control_enabled=True, keyboard=True, pointer=True, owner=USER_ID, allowlist=(BUNDLE,)):
    db.add_all([
        Tenant(id=TENANT_ID, name="Actuate Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="a@example.test", hashed_password="x"),
        User(id=OTHER_USER_ID, tenant_id=TENANT_ID, email="o@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s"),
        ChatSession(id=OTHER_SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s2"),
        TenantFeatures(
            tenant_id=TENANT_ID,
            desktop_control_enabled=control_enabled,
            keyboard_control_enabled=keyboard,
            pointer_control_enabled=pointer,
            native_control_target_allowlist=list(allowlist),
        ),
    ])
    db.commit()
    return db.query(User).filter(User.id == USER_ID).first()


def _seed_other_tenant(db):
    db.add_all([
        Tenant(id=OTHER_TENANT_ID, name="Other"),
        User(id=OTHER_TENANT_USER_ID, tenant_id=OTHER_TENANT_ID, email="x@example.test", hashed_password="x"),
        TenantFeatures(tenant_id=OTHER_TENANT_ID, desktop_control_enabled=True),
    ])
    db.commit()


def _permission_readiness(*, screen="granted", accessibility="granted", observed_at=None):
    return {
        "screen_recording": {"status": screen},
        "accessibility": {"status": accessibility},
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
    }


def _presence(connected=True, readiness=_READINESS_MISSING):
    if not connected:
        return {"connected_shells": [], "shell_devices": {}}
    if readiness is _READINESS_MISSING:
        readiness = _permission_readiness()
    payload = {
        "active_shell": SHELL_ID,
        "connected_shells": [SHELL_ID],
        "shell_capabilities": {
            SHELL_ID: {"can_observe": True, "can_control_keyboard": True, "can_control_pointer": True}
        },
        "shell_devices": {SHELL_ID: str(DEVICE_ID)},
    }
    if readiness is not None:
        payload["shell_permission_readiness"] = {SHELL_ID: readiness}
    return payload


def _patch_presence(connected=True, readiness=_READINESS_MISSING):
    return patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(connected, readiness=readiness),
    )


def _mk_grant(
    db,
    *,
    action="keyboard_type",
    capability="keyboard_control",
    status="active",
    user_id=USER_ID,
    session_id=SESSION_ID,
    tenant_id=TENANT_ID,
    remaining=1,
    expires_delta=timedelta(seconds=120),
    revoked=False,
    risk_tier="native_control",
    bundle=BUNDLE,
):
    now = datetime.now(timezone.utc)
    grant = DesktopCommandApprovalGrant(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        shell_id=SHELL_ID,
        device_id=DEVICE_ID,
        risk_tier=risk_tier,
        capability=capability,
        status=status,
        target_binding={"bundle_id": bundle, "action": action},
        max_actions=max(1, remaining),
        remaining_actions=remaining,
        approved_by_user_id=user_id,
        approved_at=now,
        expires_at=now + expires_delta,
        revoked_at=now if revoked else None,
        created_at=now,
        updated_at=now,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    return grant


def _actuate(db, grant_id, **over):
    connected = over.pop("_connected", True)
    readiness = over.pop("_readiness", _READINESS_MISSING)
    kwargs = dict(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        grant_id=grant_id,
        args={"text": "hello"},
    )
    kwargs.update(over)
    with _patch_presence(connected, readiness=readiness):
        return desktop_act.actuate_command(db, **kwargs)


def _denial(exc_info):
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured denial, got {detail!r}"
    return exc_info.value.status_code, detail["code"]


def _commands(db):
    return db.query(DesktopCommand).all()


# ── success: queued command bound to the grant ───────────────────────────────


def test_actuate_with_valid_grant_enqueues_bound_command(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured.setdefault("events", []).append((event_type, payload))
        return {"event_id": "e", "seq_no": 1}

    with patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ), _patch_presence():
        out = desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "hello"},
        )

    assert out["status"] == "queued"
    assert out["action"] == "keyboard_type"
    assert out["capability"] == "keyboard_control"
    assert out["approval_id"] == str(grant.id)
    assert out["command_status"] == "pending"
    assert out["target_bundle_id"] == BUNDLE

    cmds = _commands(db_session)
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd.status == "pending"
    assert str(cmd.approval_id) == str(grant.id)
    assert cmd.capability == "keyboard_control"
    assert cmd.tenant_id == TENANT_ID and cmd.session_id == SESSION_ID

    # grant NOT consumed at actuate (consumed at claim)
    db_session.refresh(grant)
    assert grant.status == "active" and grant.remaining_actions == 1

    # the queued event never echoes the actuation args (display-safe)
    blob = str(captured.get("events"))
    assert "hello" not in blob


def test_actuate_response_is_display_safe(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    with _patch_presence():
        out = desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "SECRET-TYPED-TEXT"},
        )
    blob = str(out)
    assert "SECRET-TYPED-TEXT" not in blob
    assert "args" not in out


# ── missing grant → approval_required (no command) ───────────────────────────


def test_actuate_no_grant_returns_approval_required(db_session):
    _seed(db_session)
    with _patch_presence():
        out = desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=uuid.uuid4(), args={"text": "x"},
        )
    assert out["status"] == "approval_required"
    assert out["command_id"] is None
    assert _commands(db_session) == []


def test_actuate_cross_tenant_grant_is_approval_required(db_session):
    _seed(db_session)
    _seed_other_tenant(db_session)
    # grant lives in the other tenant
    grant = _mk_grant(db_session, tenant_id=OTHER_TENANT_ID, user_id=OTHER_TENANT_USER_ID)
    with _patch_presence():
        out = desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "x"},
        )
    assert out["status"] == "approval_required"
    assert _commands(db_session) == []


# ── wrong grant → structured deny (no command) ───────────────────────────────


def test_actuate_wrong_owner_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session, user_id=OTHER_USER_ID)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "x"},
        )
    code, name = _denial(exc)
    assert name == "approval_binding_mismatch"
    assert _commands(db_session) == []


def test_actuate_wrong_session_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session, session_id=OTHER_SESSION_ID)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "x"},
        )
    _, name = _denial(exc)
    assert name == "approval_binding_mismatch"
    assert _commands(db_session) == []


def test_actuate_expired_grant_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    _, name = _denial(exc)
    assert name == "approval_expired"
    assert _commands(db_session) == []


def test_actuate_revoked_grant_denies(db_session):
    """Stop (#893) revokes the grant; a post-Stop actuate denies."""
    _seed(db_session)
    grant = _mk_grant(db_session, status="revoked", revoked=True)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    _, name = _denial(exc)
    assert name == "approval_revoked"
    assert _commands(db_session) == []


def test_actuate_exhausted_grant_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session, remaining=0)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    _, name = _denial(exc)
    assert name == "approval_exhausted"
    assert _commands(db_session) == []


def test_actuate_non_native_grant_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session, risk_tier="observe", capability="screenshot", action="capture_screenshot")
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    _, name = _denial(exc)
    assert name == "approval_binding_mismatch"
    assert _commands(db_session) == []


# ── safety gates: capability flag / master / allowlist / shell ───────────────


def test_actuate_capability_flag_off_denies_no_command(db_session):
    # keyboard_control_enabled OFF (default) — even with an active grant, enqueue
    # refuses; no command is created.
    _seed(db_session, keyboard=False)
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    assert exc.value.status_code == 403
    assert _commands(db_session) == []


def test_actuate_master_flag_off_denies(db_session):
    _seed(db_session, control_enabled=False)
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    assert exc.value.status_code == 403
    assert _commands(db_session) == []


def test_actuate_not_allowlisted_denies(db_session):
    # tenant opts in no bundle → effective allowlist empty → enqueue 422
    _seed(db_session, allowlist=())
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        _actuate(db_session, grant.id)
    assert exc.value.status_code == 422
    assert _commands(db_session) == []


def test_actuate_shell_offline_denies(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc, _patch_presence(connected=False):
        desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "x"},
        )
    assert exc.value.status_code == 409
    assert _commands(db_session) == []


def test_actuate_missing_permission_readiness_denies_no_command(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc:
        _actuate(db_session, grant.id, _readiness=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "permission_not_ready"
    assert _commands(db_session) == []


def test_actuate_denied_permission_readiness_denies_no_command(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    readiness = _permission_readiness(accessibility="denied")
    with pytest.raises(HTTPException) as exc:
        _actuate(db_session, grant.id, _readiness=readiness)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "permission_not_ready"
    assert _commands(db_session) == []


def test_actuate_stale_permission_readiness_denies_no_command(db_session):
    _seed(db_session)
    grant = _mk_grant(db_session)
    readiness = _permission_readiness(
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=31)
    )
    with pytest.raises(HTTPException) as exc:
        _actuate(db_session, grant.id, _readiness=readiness)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "permission_not_ready"
    assert _commands(db_session) == []


# ── routes: user-JWT + internal-key (no minting via internal) ────────────────


def _client(db, user):
    app = FastAPI()
    app.include_router(desktop_control_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app)


def test_actuate_route_queues_for_authenticated_user(db_session):
    user = _seed(db_session)
    grant = _mk_grant(db_session)
    client = _client(db_session, user)
    with _patch_presence():
        resp = client.post(
            "/api/v1/desktop-control/commands/actuate",
            json={"session_id": str(SESSION_ID), "grant_id": str(grant.id), "args": {"text": "hi"}},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    assert body["approval_id"] == str(grant.id)
    assert "hi" not in resp.text  # display-safe: args never echoed
    assert len(_commands(db_session)) == 1


def test_actuate_route_approval_required_when_no_grant(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    resp = client.post(
        "/api/v1/desktop-control/commands/actuate",
        json={"session_id": str(SESSION_ID), "grant_id": str(uuid.uuid4()), "args": {"text": "hi"}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approval_required"
    assert _commands(db_session) == []


def test_internal_actuate_requires_internal_key(db_session):
    user = _seed(db_session)
    grant = _mk_grant(db_session)
    client = _client(db_session, user)
    resp = client.post(
        "/api/v1/desktop-control/internal/commands/actuate",
        json={"session_id": str(SESSION_ID), "grant_id": str(grant.id)},
        headers={"X-Internal-Key": "wrong-key", "X-Tenant-Id": str(TENANT_ID), "X-User-Id": str(USER_ID)},
    )
    assert resp.status_code == 401


def test_internal_actuate_consumes_grant_never_mints(db_session):
    user = _seed(db_session)
    grant = _mk_grant(db_session)
    grants_before = db_session.query(DesktopCommandApprovalGrant).count()
    client = _client(db_session, user)
    with _patch_presence():
        resp = client.post(
            "/api/v1/desktop-control/internal/commands/actuate",
            json={"session_id": str(SESSION_ID), "grant_id": str(grant.id), "args": {"text": "hi"}},
            headers={
                "X-Internal-Key": settings.API_INTERNAL_KEY,
                "X-Tenant-Id": str(TENANT_ID),
                "X-User-Id": str(USER_ID),
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    # the internal path NEVER mints a grant — count unchanged
    assert db_session.query(DesktopCommandApprovalGrant).count() == grants_before


def test_no_internal_actuate_can_forge_a_grant_for_another_user(db_session):
    # An internal caller forging X-User-Id can only act on a grant owned by THAT
    # user; a grant owned by USER_ID cannot be actuated as OTHER_USER_ID.
    user = _seed(db_session)
    grant = _mk_grant(db_session, user_id=USER_ID)
    client = _client(db_session, user)
    with _patch_presence():
        resp = client.post(
            "/api/v1/desktop-control/internal/commands/actuate",
            json={"session_id": str(SESSION_ID), "grant_id": str(grant.id)},
            headers={
                "X-Internal-Key": settings.API_INTERNAL_KEY,
                "X-Tenant-Id": str(TENANT_ID),
                "X-User-Id": str(OTHER_USER_ID),
            },
        )
    # OTHER_USER does not own the grant → structured deny, no command
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "approval_binding_mismatch"
    assert _commands(db_session) == []


def test_actuate_malformed_args_is_structured_422_no_command(db_session):
    # over-long keyboard text fails _normalize_native_control_args inside the
    # shared enqueue → structured 422 deny (not an opaque 500), no command.
    _seed(db_session)
    grant = _mk_grant(db_session)
    with pytest.raises(HTTPException) as exc, _patch_presence():
        desktop_act.actuate_command(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
            grant_id=grant.id, args={"text": "x" * 5000},
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "invalid_actuation_args"
    # the over-long text is never echoed in the denial
    assert "xxxx" not in str(exc.value.detail)
    assert _commands(db_session) == []
