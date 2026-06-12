"""Luna P5.5 — user approval surface tests (approve / deny / list).

Covers `desktop_act.list_pending_approval_requests` /
`approve_desktop_grant_request` / `deny_desktop_grant_request` and the user-JWT
routes: approve mints exactly ONE bounded active grant (owner = authenticated
user), deny is terminal and creates no grant, both are tenant/owner scoped and
fail-closed (cross-tenant, wrong-user, expired, duplicate), events are
display-safe, and the claim path only ever sees the active grant (never a
pending-only request).
"""
from __future__ import annotations

import json
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
from app.models.desktop_approval_request import DesktopApprovalRequest
from app.models.desktop_command_approval_grant import DesktopCommandApprovalGrant
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import desktop_act
from app.services.desktop_act import DesktopGrantRequestDenialCode

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222223")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
DEVICE_ID = "88888888-8888-8888-8888-888888888888"
BUNDLE = "net.whatsapp.WhatsApp"

OTHER_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TENANT_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _allowlist_floor(monkeypatch):
    # The native-control target allowlist is (per-tenant ∩ global floor). Put the
    # canary bundle in the floor so an opted-in tenant can be approved.
    monkeypatch.setattr(
        settings, "DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST", [BUNDLE], raising=False
    )


def _seed(db, *, control_enabled: bool = True, owner=USER_ID, allowlist=(BUNDLE,)):
    db.add_all([
        Tenant(id=TENANT_ID, name="Approval Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="a@example.test", hashed_password="x"),
        User(id=OTHER_USER_ID, tenant_id=TENANT_ID, email="o@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s"),
        TenantFeatures(
            tenant_id=TENANT_ID,
            desktop_control_enabled=control_enabled,
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


def _presence():
    return {
        "active_shell": SHELL_ID,
        "connected_shells": [SHELL_ID],
        "shell_capabilities": {SHELL_ID: {"can_observe": True, "can_control_keyboard": True}},
        "shell_devices": {SHELL_ID: DEVICE_ID},
    }


def _patch_presence(connected: bool = True):
    snap = _presence() if connected else {"connected_shells": [], "shell_devices": {}}
    return patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=snap,
    )


def _make_pending(db, *, action="keyboard_type", user_id=USER_ID, session_id=SESSION_ID):
    kwargs = dict(
        tenant_id=TENANT_ID,
        user_id=user_id,
        session_id=session_id,
        action=action,
    )
    if action not in {"capture_screenshot", "get_active_app", "read_clipboard"}:
        kwargs["target_bundle_id"] = BUNDLE
    with _patch_presence():
        out = desktop_act.request_desktop_grant(db, **kwargs)
    return uuid.UUID(out["request_id"])


def _approve(db, request_id, **over):
    kwargs = dict(tenant_id=TENANT_ID, user_id=USER_ID, request_id=request_id)
    kwargs.update(over)
    with _patch_presence():
        return desktop_act.approve_desktop_grant_request(db, **kwargs)


def _denial(exc_info):
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured denial, got {detail!r}"
    return exc_info.value.status_code, detail["code"]


def _active_grants(db):
    return db.query(DesktopCommandApprovalGrant).filter(
        DesktopCommandApprovalGrant.status == "active"
    ).all()


# ── approve: exactly one bounded active grant ────────────────────────────────


def test_approve_mints_exactly_one_active_bounded_grant(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    assert _active_grants(db_session) == []  # claim path sees nothing yet

    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured.setdefault("events", []).append((event_type, payload))
        return {"event_id": "e", "seq_no": 1}

    with patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ):
        out = _approve(db_session, rid, max_actions=2, expires_in_seconds=120)

    # request flipped to approved + bound to the grant
    assert out["status"] == "approved"
    assert out["grant_present"] is True
    assert out["grant_status"] == "active"
    assert out["risk_tier"] == "native_control"
    assert out["capability"] == "keyboard_control"
    assert out["max_actions"] == 2

    # exactly one active grant exists, bound to tenant/session/device + owner
    grants = _active_grants(db_session)
    assert len(grants) == 1
    g = grants[0]
    assert g.tenant_id == TENANT_ID
    assert str(g.user_id) == str(USER_ID)
    assert str(g.approved_by_user_id) == str(USER_ID)
    assert g.session_id == SESSION_ID
    assert g.shell_id == SHELL_ID
    assert str(g.device_id) == DEVICE_ID
    assert g.risk_tier == "native_control"
    assert g.capability == "keyboard_control"
    assert g.target_binding.get("bundle_id") == BUNDLE
    assert g.max_actions == 2 and g.remaining_actions == 2

    # the approved event is display-safe (ids/status/bundle only, no payload bag)
    approved = [p for (t, p) in captured["events"] if t == "desktop_grant_approved"]
    assert len(approved) == 1
    blob = str(approved[0])
    assert "payload" not in approved[0]
    assert "secret" not in blob.lower()


def test_approve_observe_request_mints_observe_grant_without_target(db_session):
    _seed(db_session)
    rid = _make_pending(db_session, action="capture_screenshot")

    out = _approve(db_session, rid, max_actions=1, expires_in_seconds=60)

    assert out["status"] == "approved"
    assert out["grant_present"] is True
    assert out["risk_tier"] == "observe"
    assert out["capability"] == "screenshot"
    assert out["target_bundle_id"] is None

    grants = _active_grants(db_session)
    assert len(grants) == 1
    grant = grants[0]
    assert grant.risk_tier == "observe"
    assert grant.capability == "screenshot"
    assert grant.target_binding == {}
    assert grant.remaining_actions == 1


def test_approve_logs_byte_free_rl_decision(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)

    with patch("app.services.desktop_act.rl_experience_service.log_experience") as log_exp:
        out = _approve(db_session, rid, max_actions=1, expires_in_seconds=60)

    log_exp.assert_called_once()
    kwargs = log_exp.call_args.kwargs
    assert kwargs["tenant_id"] == TENANT_ID
    assert kwargs["trajectory_id"] == SESSION_ID
    assert kwargs["decision_point"] == "desktop_control_decision"
    assert kwargs["state"] == {
        "surface": "desktop_grant_decision",
        "session_id": str(SESSION_ID),
        "source": "user_jwt",
    }
    assert kwargs["action"]["outcome"] == "approved"
    assert kwargs["action"]["action"] == "keyboard_type"
    assert kwargs["action"]["capability"] == "keyboard_control"
    assert kwargs["action"]["request_id"] == str(rid)
    assert kwargs["action"]["grant_id"] == out["grant_id"]
    assert kwargs["state_text"] is None


def test_deny_logs_byte_free_rl_decision_without_reason(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)

    with patch("app.services.desktop_act.rl_experience_service.log_experience") as log_exp:
        out = desktop_act.deny_desktop_grant_request(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            request_id=rid,
            reason="LEAK_DENY_REASON",
        )

    assert out["status"] == "denied"
    log_exp.assert_called_once()
    kwargs = log_exp.call_args.kwargs
    assert kwargs["state"]["surface"] == "desktop_grant_decision"
    assert kwargs["action"]["outcome"] == "denied"
    assert kwargs["action"]["request_id"] == str(rid)
    assert kwargs["state_text"] is None
    assert "LEAK_DENY_REASON" not in json.dumps(kwargs, default=str)


def test_claim_path_ignores_pending_only_rows(db_session):
    """The grant claim path consumes only active grants; a pending request alone
    authorizes nothing."""
    _seed(db_session)
    rid = _make_pending(db_session)
    # pending request exists, but zero active grants → claim path finds nothing
    assert db_session.query(DesktopApprovalRequest).count() == 1
    assert _active_grants(db_session) == []
    _approve(db_session, rid)
    # after approval exactly one active grant is claimable
    assert len(_active_grants(db_session)) == 1


def test_duplicate_approve_is_fail_closed_no_second_grant(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    _approve(db_session, rid)
    assert len(_active_grants(db_session)) == 1
    # second approve of the same request → 409 not-pending, no second grant
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid)
    status_code, code = _denial(exc)
    assert status_code == 409
    assert code == DesktopGrantRequestDenialCode.REQUEST_NOT_PENDING.value
    assert len(_active_grants(db_session)) == 1


def test_approve_desktop_control_disabled_denies(db_session):
    _seed(db_session, control_enabled=False)
    # Request creation also needs the master flag, so build a pending row directly
    # to isolate the approve-time master-flag re-check.
    now = datetime.now(timezone.utc)
    row = DesktopApprovalRequest(
        tenant_id=TENANT_ID, user_id=USER_ID, session_id=SESSION_ID,
        shell_id=SHELL_ID, action="keyboard_type", capability="keyboard_control",
        target_binding={"bundle_id": BUNDLE}, status="pending",
        requested_by_user_id=USER_ID, created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    db_session.add(row)
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, row.id)
    assert exc.value.status_code == 403
    assert _active_grants(db_session) == []


def test_approve_expired_request_denies(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    row = db_session.query(DesktopApprovalRequest).filter(
        DesktopApprovalRequest.id == rid
    ).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid)
    status_code, code = _denial(exc)
    assert status_code == 409
    assert code == DesktopGrantRequestDenialCode.REQUEST_EXPIRED.value
    assert _active_grants(db_session) == []


def test_approve_wrong_user_is_not_found(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid, user_id=OTHER_USER_ID)
    status_code, code = _denial(exc)
    assert status_code == 404
    assert code == DesktopGrantRequestDenialCode.REQUEST_NOT_FOUND.value
    assert _active_grants(db_session) == []


def test_approve_cross_tenant_is_not_found(db_session):
    _seed(db_session)
    _seed_other_tenant(db_session)
    rid = _make_pending(db_session)
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid, tenant_id=OTHER_TENANT_ID, user_id=OTHER_TENANT_USER_ID)
    status_code, code = _denial(exc)
    assert status_code == 404


def test_approve_disconnected_shell_denies_no_grant(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    with _patch_presence(connected=False), pytest.raises(HTTPException) as exc:
        desktop_act.approve_desktop_grant_request(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid
        )
    assert exc.value.status_code == 409  # shell not connected
    assert _active_grants(db_session) == []


def test_approve_bundle_not_allowlisted_denies(db_session):
    # tenant opts in NO bundle → effective allowlist empty → 422, no grant
    _seed(db_session, allowlist=())
    rid = _make_pending(db_session)
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid)
    assert exc.value.status_code == 422
    assert _active_grants(db_session) == []


# ── P5.4c: status poll exposes grant_id only after human approval ────────────


def test_status_poll_exposes_grant_id_only_after_human_approval(db_session):
    """P5.4c chat-loop primitive: the agent's owner-scoped status poll reflects
    the grant_id once a human approves — so a CLI-subprocess agent (which polls
    tools, not SSE) can actuate against it. The request/poll path mints NO grant;
    only the human approve does."""
    _seed(db_session)
    rid = _make_pending(db_session)

    # before approval — no grant reference, no grant row
    before = desktop_act.get_desktop_grant_request_status(
        db_session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid
    )
    assert before["grant_present"] is False
    assert before["grant_id"] is None
    assert _active_grants(db_session) == []

    # human approves — the ONLY mint path — exactly one grant
    approved = _approve(db_session, rid)
    grant_id = approved["grant_id"]
    assert len(_active_grants(db_session)) == 1

    # after approval — the same owner sees the SAME grant_id it must actuate with
    after = desktop_act.get_desktop_grant_request_status(
        db_session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid
    )
    assert after["status"] == "approved"
    assert after["grant_present"] is True
    assert after["grant_id"] == grant_id

    # a different owner still gets uniform not-found — no grant_id oracle
    with pytest.raises(HTTPException) as exc:
        desktop_act.get_desktop_grant_request_status(
            db_session, tenant_id=TENANT_ID, user_id=OTHER_USER_ID, request_id=rid
        )
    assert exc.value.status_code == 404


# ── deny: terminal, no grant ─────────────────────────────────────────────────


def test_deny_is_terminal_and_creates_no_grant(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured.setdefault("events", []).append((event_type, payload))
        return {"event_id": "e", "seq_no": 1}

    with patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ):
        out = desktop_act.deny_desktop_grant_request(
            db_session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid,
            reason="not now",
        )
    assert out["status"] == "denied"
    assert out["grant_present"] is False
    assert _active_grants(db_session) == []
    row = db_session.query(DesktopApprovalRequest).filter(
        DesktopApprovalRequest.id == rid
    ).first()
    assert row.status == "denied" and row.decided_at is not None and row.grant_id is None
    denied = [p for (t, p) in captured["events"] if t == "desktop_grant_denied"]
    assert len(denied) == 1 and denied[0]["deny_reason"] == "not now"


def test_deny_then_approve_is_fail_closed(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    desktop_act.deny_desktop_grant_request(
        db_session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid
    )
    with pytest.raises(HTTPException) as exc:
        _approve(db_session, rid)
    status_code, code = _denial(exc)
    assert status_code == 409
    assert code == DesktopGrantRequestDenialCode.REQUEST_NOT_PENDING.value
    assert _active_grants(db_session) == []


# ── list scoping ─────────────────────────────────────────────────────────────


def test_list_scoped_to_user_and_pending(db_session):
    _seed(db_session)
    rid = _make_pending(db_session)
    # another user's request in the same tenant is not listed for USER_ID
    other_session = uuid.uuid4()
    db_session.add(ChatSession(id=other_session, tenant_id=TENANT_ID, owner_user_id=OTHER_USER_ID, title="o"))
    db_session.commit()
    _make_pending(db_session, user_id=OTHER_USER_ID, session_id=other_session)

    rows = desktop_act.list_pending_approval_requests(
        db_session, tenant_id=TENANT_ID, user_id=USER_ID
    )
    assert len(rows) == 1 and rows[0]["request_id"] == str(rid)

    # approved/denied requests drop off the pending list
    _approve(db_session, rid)
    assert desktop_act.list_pending_approval_requests(
        db_session, tenant_id=TENANT_ID, user_id=USER_ID
    ) == []


# ── routes: user-JWT only; reject internal-key ───────────────────────────────


def _client(db, user):
    app = FastAPI()
    app.include_router(desktop_control_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app)


def test_approve_route_mints_grant_for_authenticated_user(db_session):
    user = _seed(db_session)
    rid = _make_pending(db_session)
    client = _client(db_session, user)
    with _patch_presence():
        resp = client.post(
            f"/api/v1/desktop-control/grants/requests/{rid}/approve",
            json={"max_actions": 1, "expires_in_seconds": 60},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["grant_status"] == "active"
    assert body["grant_id"]
    assert "storage_path" not in resp.text
    assert len(_active_grants(db_session)) == 1

    status_resp = client.get(
        f"/api/v1/desktop-control/grants/requests/{rid}",
    )
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["status"] == "approved"
    assert status_body["grant_id"] == body["grant_id"]


def test_deny_route_is_terminal(db_session):
    user = _seed(db_session)
    rid = _make_pending(db_session)
    client = _client(db_session, user)
    resp = client.post(
        f"/api/v1/desktop-control/grants/requests/{rid}/deny",
        json={"reason": "no"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"
    assert _active_grants(db_session) == []


def test_list_route_returns_pending(db_session):
    user = _seed(db_session)
    rid = _make_pending(db_session)
    client = _client(db_session, user)
    resp = client.get("/api/v1/desktop-control/grants/requests")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1 and body[0]["request_id"] == str(rid)


def test_approve_route_has_no_internal_key_twin(db_session):
    """The approve/deny routes are user-JWT only — there is no /internal/ grant
    minting path, so an MCP_API_KEY-only caller cannot approve."""
    from app.api.v1 import desktop_control
    paths = {getattr(r, "path", "") for r in desktop_control.router.routes}
    assert "/desktop-control/grants/requests/{request_id}/approve" in paths
    assert "/desktop-control/internal/grants/requests/{request_id}/approve" not in paths
    assert not any("approve" in p and "internal" in p for p in paths)
    assert not any("deny" in p and "internal" in p for p in paths)


# ── concurrency: exactly-one-grant under a real Postgres row lock ─────────────
# Gated `integration` — the SELECT … FOR UPDATE serialization is a Postgres
# guarantee; SQLite no-ops with_for_update(), so this only proves the lock branch
# in CI's Postgres lane (per the repo "run IO tests vs LIVE Postgres" lesson).


@pytest.mark.integration
def test_concurrent_approve_mints_exactly_one_grant(db_session):
    import threading

    if engine.dialect.name != "postgresql":
        pytest.skip("requires Postgres SELECT FOR UPDATE row locking")

    _seed(db_session)
    rid = _make_pending(db_session)

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def worker():
        session = SessionLocal()
        try:
            barrier.wait(timeout=10)
            try:
                out = desktop_act.approve_desktop_grant_request(
                    session, tenant_id=TENANT_ID, user_id=USER_ID, request_id=rid
                )
                with lock:
                    results.append(("ok", out["grant_id"]))
            except HTTPException as exc:
                with lock:
                    results.append(("denied", exc.status_code))
        finally:
            session.close()

    with _patch_presence():
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

    oks = [r for r in results if r[0] == "ok"]
    denied = [r for r in results if r[0] == "denied"]
    assert len(oks) == 1, f"expected exactly one approve to win, got {results}"
    assert len(denied) == 1 and denied[0][1] == 409
    # exactly one active grant exists in the DB
    assert len(_active_grants(db_session)) == 1
