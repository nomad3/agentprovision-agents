"""Luna P5.4b — agent-facing pending desktop approval request tests.

Covers `desktop_act.request_desktop_grant` / `get_desktop_grant_request_status`
and the thin `alpha desktop grant request|status` routes: the request records a
PENDING row, is scoped + display-safe, fails closed when desktop control is off,
rejects non-native actions, and — critically — NEVER mints an approval grant or
enqueues a command (no actuation path).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.api import deps
from app.api.v1.desktop_control import router as desktop_control_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.chat import ChatSession
from app.models.desktop_approval_request import DesktopApprovalRequest
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import desktop_act
from app.services.desktop_act import DesktopGrantRequestDenialCode

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222223")
OTHER_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111112")
CROSS_TENANT_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222224")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
DEVICE_ID = "88888888-8888-8888-8888-888888888888"
BUNDLE = "net.whatsapp.WhatsApp"


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed(db, *, control_enabled: bool = True, owner=USER_ID):
    db.add_all([
        Tenant(id=TENANT_ID, name="Act Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="a@example.test", hashed_password="x"),
        User(id=OTHER_USER_ID, tenant_id=TENANT_ID, email="o@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s"),
        TenantFeatures(tenant_id=TENANT_ID, desktop_control_enabled=control_enabled),
    ])
    db.commit()
    return db.query(User).filter(User.id == USER_ID).first()


def _presence():
    return {
        "active_shell": SHELL_ID,
        "connected_shells": [SHELL_ID],
        "shell_capabilities": {SHELL_ID: {"can_observe": True}},
        "shell_devices": {SHELL_ID: DEVICE_ID},
    }


def _patch_presence():
    return patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_presence(),
    )


def _req(db, **over):
    kwargs = dict(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        action="keyboard_type",
        target_bundle_id=BUNDLE,
    )
    kwargs.update(over)
    with _patch_presence():
        return desktop_act.request_desktop_grant(db, **kwargs)


def _denial(exc_info):
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured denial, got {detail!r}"
    return exc_info.value.status_code, detail["code"]


# ── service: success + safety invariants ─────────────────────────────────────


def test_request_creates_pending_row_and_no_grant_or_command(db_session):
    _seed(db_session)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured["event_type"] = event_type
        captured["payload"] = payload
        return {"event_id": "evt-1", "seq_no": 1}

    with patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ):
        out = _req(db_session)

    assert out["status"] == "pending"
    assert out["action"] == "keyboard_type"
    assert out["capability"] == "keyboard_control"
    assert out["shell_id"] == SHELL_ID
    assert out["target_bundle_id"] == BUNDLE
    assert out["grant_present"] is False

    # a pending request row exists ...
    row = db_session.query(DesktopApprovalRequest).filter(
        DesktopApprovalRequest.id == uuid.UUID(out["request_id"])
    ).first()
    assert row is not None and row.status == "pending"
    assert row.grant_id is None

    # ... but NO approval grant and NO command were created (no actuation path)
    assert db_session.query(DesktopCommandApprovalGrant).count() == 0
    assert db_session.query(DesktopCommand).count() == 0

    # the session event is display-safe (byte-free, no payload bag)
    assert captured["event_type"] == "desktop_grant_requested"
    assert "payload" not in captured["payload"]
    assert captured["payload"]["status"] == "pending"


@pytest.mark.parametrize(
    "action,capability",
    [
        ("pointer_move", "pointer_control"),
        ("pointer_click", "pointer_control"),
        ("keyboard_type", "keyboard_control"),
        ("keyboard_key_chord", "keyboard_control"),
    ],
)
def test_each_native_action_maps_to_capability(db_session, action, capability):
    _seed(db_session)
    out = _req(db_session, action=action)
    assert out["capability"] == capability


def test_reason_is_capped_and_stripped(db_session):
    _seed(db_session)
    out = _req(db_session, reason="  " + "x" * 400 + "  ")
    assert len(out["reason"]) == 280


# ── service: fail-closed gates ───────────────────────────────────────────────


def test_desktop_control_disabled_denies(db_session):
    _seed(db_session, control_enabled=False)
    with pytest.raises(HTTPException) as exc:
        _req(db_session)
    # master-flag gate raises the desktop-control 403 before request creation
    assert exc.value.status_code == 403
    assert db_session.query(DesktopApprovalRequest).count() == 0


def test_non_native_action_is_rejected(db_session):
    _seed(db_session)
    with pytest.raises(HTTPException) as exc:
        _req(db_session, action="capture_screenshot")
    status_code, code = _denial(exc)
    assert status_code == 422
    assert code == DesktopGrantRequestDenialCode.ACTION_NOT_REQUESTABLE.value
    assert db_session.query(DesktopApprovalRequest).count() == 0


def test_invalid_bundle_is_rejected(db_session):
    _seed(db_session)
    with pytest.raises(HTTPException) as exc:
        _req(db_session, target_bundle_id="../etc/passwd")
    status_code, code = _denial(exc)
    assert status_code == 422
    assert code == DesktopGrantRequestDenialCode.INVALID_TARGET_BUNDLE.value


def test_session_not_owned_is_denied(db_session):
    _seed(db_session, owner=OTHER_USER_ID)
    with pytest.raises(HTTPException) as exc:
        _req(db_session)
    assert exc.value.status_code == 403


def test_cross_tenant_session_owner_is_denied_before_pending_row(db_session):
    _seed(db_session, owner=CROSS_TENANT_USER_ID)
    db_session.add(
        Tenant(id=OTHER_TENANT_ID, name="Other Tenant"),
    )
    db_session.add(
        User(
            id=CROSS_TENANT_USER_ID,
            tenant_id=OTHER_TENANT_ID,
            email="cross@example.test",
            hashed_password="x",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        _req(db_session, user_id=CROSS_TENANT_USER_ID)
    assert exc.value.status_code == 404
    assert db_session.query(DesktopApprovalRequest).count() == 0


# ── service: status projection + scoping ─────────────────────────────────────


def test_status_poll_returns_pending(db_session):
    _seed(db_session)
    out = _req(db_session)
    status_out = desktop_act.get_desktop_grant_request_status(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request_id=uuid.UUID(out["request_id"]),
    )
    assert status_out["status"] == "pending"
    assert status_out["request_id"] == out["request_id"]


def test_status_poll_grant_id_is_null_while_pending(db_session):
    # P5.4c: the grant reference is null until a human approves; the request and
    # status-poll paths mint no grant (grant_id is a reflection, not a mint).
    _seed(db_session)
    out = _req(db_session)
    assert out["grant_id"] is None
    status_out = desktop_act.get_desktop_grant_request_status(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request_id=uuid.UUID(out["request_id"]),
    )
    assert status_out["grant_present"] is False
    assert status_out["grant_id"] is None
    assert db_session.query(DesktopCommandApprovalGrant).count() == 0


def test_status_wrong_user_is_uniform_not_found(db_session):
    _seed(db_session)
    out = _req(db_session)
    with pytest.raises(HTTPException) as exc:
        desktop_act.get_desktop_grant_request_status(
            db_session,
            tenant_id=TENANT_ID,
            user_id=OTHER_USER_ID,
            request_id=uuid.UUID(out["request_id"]),
        )
    status_code, code = _denial(exc)
    assert status_code == 404
    assert code == DesktopGrantRequestDenialCode.REQUEST_NOT_FOUND.value


def test_status_wrong_tenant_is_uniform_not_found(db_session):
    _seed(db_session)
    out = _req(db_session)
    with pytest.raises(HTTPException) as exc:
        desktop_act.get_desktop_grant_request_status(
            db_session,
            tenant_id=uuid.uuid4(),
            user_id=USER_ID,
            request_id=uuid.UUID(out["request_id"]),
        )
    status_code, code = _denial(exc)
    assert status_code == 404


def test_pending_past_ttl_projects_expired(db_session):
    from datetime import datetime, timedelta, timezone

    _seed(db_session)
    out = _req(db_session)
    row = db_session.query(DesktopApprovalRequest).filter(
        DesktopApprovalRequest.id == uuid.UUID(out["request_id"])
    ).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    status_out = desktop_act.get_desktop_grant_request_status(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        request_id=row.id,
    )
    assert status_out["status"] == "expired"


# ── thin routes ──────────────────────────────────────────────────────────────


def _client(db, user):
    app = FastAPI()
    app.include_router(desktop_control_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app)


def test_request_route_creates_pending(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    with _patch_presence():
        resp = client.post(
            "/api/v1/desktop-control/grants/request",
            json={
                "session_id": str(SESSION_ID),
                "action": "keyboard_type",
                "target_bundle_id": BUNDLE,
                "reason": "send a message",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["capability"] == "keyboard_control"
    assert body["grant_id"] is None
    assert "storage_path" not in resp.text


def test_request_route_rejects_arbitrary_payload_bag(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    resp = client.post(
        "/api/v1/desktop-control/grants/request",
        json={
            "session_id": str(SESSION_ID),
            "action": "keyboard_type",
            "target_bundle_id": BUNDLE,
            "payload": {"args": {"text": "secret"}},
        },
    )
    # extra="forbid" → 422, the reduced-metadata-only contract holds
    assert resp.status_code == 422


def test_status_route_round_trips(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    with _patch_presence():
        created = client.post(
            "/api/v1/desktop-control/grants/request",
            json={
                "session_id": str(SESSION_ID),
                "action": "pointer_click",
                "target_bundle_id": BUNDLE,
            },
        ).json()
    resp = client.get(
        f"/api/v1/desktop-control/grants/requests/{created['request_id']}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["grant_id"] is None


def test_internal_request_route_requires_internal_key(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    resp = client.post(
        "/api/v1/desktop-control/internal/grants/request",
        json={
            "session_id": str(SESSION_ID),
            "action": "keyboard_type",
            "target_bundle_id": BUNDLE,
        },
        headers={
            "X-Internal-Key": "wrong-key",
            "X-Tenant-Id": str(TENANT_ID),
            "X-User-Id": str(USER_ID),
        },
    )
    assert resp.status_code == 401


def test_internal_request_route_creates_pending_for_mcp(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured["payload"] = payload
        return {"event_id": "evt-1", "seq_no": 1}

    with _patch_presence(), patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ):
        resp = client.post(
            "/api/v1/desktop-control/internal/grants/request",
            json={
                "session_id": str(SESSION_ID),
                "action": "keyboard_type",
                "target_bundle_id": BUNDLE,
            },
            headers={
                "X-Internal-Key": settings.API_INTERNAL_KEY,
                "X-Tenant-Id": str(TENANT_ID),
                "X-User-Id": str(USER_ID),
            },
        )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    # the MCP path tags the session event source as `mcp` (not `alpha`)
    assert captured["payload"]["requested_via"] == "mcp"
    assert db_session.query(DesktopApprovalRequest).count() == 1
