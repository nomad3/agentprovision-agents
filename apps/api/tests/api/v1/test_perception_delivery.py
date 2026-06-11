"""Luna P5.3b — planner-safe perception delivery tests.

Covers `perception_delivery.fetch_planner_safe_bytes` / `artifact_status` and
the thin `alpha desktop observe` routes: every fail-closed gate (tenant,
session, shell, ownership, expiry, redaction status, raw hard-delete proof,
master desktop_control_enabled re-check), the "raw storage_path is never
served" invariant (the DB-stored path is never the filesystem authority), and
byte-free/display-safe outputs everywhere except the reviewed redacted payload.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import deps
from app.api.v1.desktop_control import router as desktop_control_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.chat import ChatSession
from app.models.perception_artifact import PerceptionArtifact
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import perception_delivery
from app.services import perception_storage
from app.services.perception_delivery import PerceptionFetchDenialCode

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222223")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER_SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333334")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
OTHER_SHELL_ID = "desktop-99999999-9999-9999-9999-999999999999"

OTHER_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TENANT_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OTHER_TENANT_SESSION_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

REDACTED_PNG = b"\x89PNG\r\n\x1a\n" + b"REDACTED-PLANNER-SAFE" * 8
RAW_PNG = b"\x89PNG\r\n\x1a\n" + b"RAW-SECRET-DO-NOT-SERVE" * 8


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _quarantine_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSERVATION_QUARANTINE_ROOT", str(tmp_path / "observations"))


def _seed(db, *, control_enabled: bool = True, owner=USER_ID):
    db.add_all([
        Tenant(id=TENANT_ID, name="Delivery Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="d@example.test", hashed_password="x"),
        User(id=OTHER_USER_ID, tenant_id=TENANT_ID, email="o@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s"),
        ChatSession(id=OTHER_SESSION_ID, tenant_id=TENANT_ID, owner_user_id=USER_ID, title="s2"),
        TenantFeatures(tenant_id=TENANT_ID, desktop_control_enabled=control_enabled),
    ])
    db.commit()
    return db.query(User).filter(User.id == USER_ID).first()


def _seed_other_tenant(db):
    db.add_all([
        Tenant(id=OTHER_TENANT_ID, name="Other Tenant"),
        User(
            id=OTHER_TENANT_USER_ID,
            tenant_id=OTHER_TENANT_ID,
            email="x@example.test",
            hashed_password="x",
        ),
        ChatSession(
            id=OTHER_TENANT_SESSION_ID,
            tenant_id=OTHER_TENANT_ID,
            owner_user_id=OTHER_TENANT_USER_ID,
            title="x",
        ),
        TenantFeatures(tenant_id=OTHER_TENANT_ID, desktop_control_enabled=True),
    ])
    db.commit()


_CANONICAL = object()


def _mk_artifact(
    db,
    *,
    tenant_id=TENANT_ID,
    session_id=SESSION_ID,
    shell_id=SHELL_ID,
    status="planner_safe",
    raw_deleted=True,
    expired=False,
    deleted=False,
    write_redacted=True,
    redacted_path=_CANONICAL,
    write_raw=False,
    size=None,
    sha=None,
):
    artifact_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    canonical_rel = perception_storage.redacted_relpath(tenant_id, session_id, artifact_id)
    root = perception_storage.quarantine_root()
    if write_redacted:
        abspath = os.path.join(root, canonical_rel)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "wb") as fh:
            fh.write(REDACTED_PNG)
    raw_rel = perception_storage.artifact_relpath(tenant_id, session_id, artifact_id)
    if write_raw:
        raw_abs = os.path.join(root, raw_rel)
        os.makedirs(os.path.dirname(raw_abs), exist_ok=True)
        with open(raw_abs, "wb") as fh:
            fh.write(RAW_PNG)
    row = PerceptionArtifact(
        id=artifact_id,
        tenant_id=tenant_id,
        session_id=session_id,
        shell_id=shell_id,
        device_id=None,
        artifact_type="screenshot",
        storage_path=raw_rel,
        sha256=sha or hashlib.sha256(REDACTED_PNG).hexdigest(),
        size_bytes=size if size is not None else len(REDACTED_PNG),
        redaction_status=status,
        expires_at=now + (timedelta(minutes=-5) if expired else timedelta(minutes=10)),
        created_at=now,
        deleted_at=now if deleted else None,
        redacted_storage_path=canonical_rel if redacted_path is _CANONICAL else redacted_path,
        redacted_at=now if status == "planner_safe" else None,
        raw_deleted_at=now if raw_deleted else None,
        redaction_meta=(
            {"verdict": "planner_safe", "region_count": 1, "redact_count": 1, "reasons": []}
            if status == "planner_safe"
            else None
        ),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _fetch(db, **over):
    kwargs = dict(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        artifact_id=None,
        shell_id=None,
    )
    kwargs.update(over)
    return perception_delivery.fetch_planner_safe_bytes(db, **kwargs)


def _denial(exc_info) -> tuple[int, str]:
    detail = exc_info.value.detail
    assert isinstance(detail, dict), f"expected structured denial, got {detail!r}"
    return exc_info.value.status_code, detail["code"]


# ── success path ─────────────────────────────────────────────────────────────


def test_successful_fetch_returns_redacted_bytes_and_byte_free_event(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured["event_type"] = event_type
        captured["payload"] = payload
        return {"event_id": "evt-1", "seq_no": 1}

    with patch(
        "app.services.desktop_control_service.publish_session_event",
        side_effect=fake_publish,
    ):
        artifact, data = _fetch(db_session, artifact_id=row.id)

    assert data == REDACTED_PNG
    assert artifact.id == row.id

    # delivery audit is BYTE-FREE and path-free
    assert captured["event_type"] == "resource_referenced"
    blob = json.dumps(captured["payload"])
    assert captured["payload"]["resource_id"] == str(row.id)
    assert captured["payload"]["delivered_via"] == "alpha"
    assert "storage_path" not in blob
    assert ".png" not in blob
    assert "REDACTED-PLANNER-SAFE" not in blob
    assert "RAW-SECRET" not in blob


def test_fetch_with_matching_shell_id_succeeds(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session)
    _, data = _fetch(db_session, artifact_id=row.id, shell_id=SHELL_ID)
    assert data == REDACTED_PNG


# ── scope gates ──────────────────────────────────────────────────────────────


def test_wrong_tenant_is_uniform_not_found(db_session):
    _seed(db_session)
    _seed_other_tenant(db_session)
    row = _mk_artifact(db_session)
    with pytest.raises(HTTPException) as exc:
        _fetch(
            db_session,
            tenant_id=OTHER_TENANT_ID,
            user_id=OTHER_TENANT_USER_ID,
            session_id=OTHER_TENANT_SESSION_ID,
            artifact_id=row.id,
        )
    status, code = _denial(exc)
    assert status == 404
    assert code == PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND.value


def test_wrong_session_is_uniform_not_found(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session)  # bound to SESSION_ID
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, session_id=OTHER_SESSION_ID, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 404
    assert code == PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND.value


def test_wrong_shell_is_uniform_not_found(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id, shell_id=OTHER_SHELL_ID)
    status, code = _denial(exc)
    assert status == 404
    assert code == PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND.value


def test_session_not_owned_by_user_is_denied(db_session):
    _seed(db_session, owner=OTHER_USER_ID)
    row = _mk_artifact(db_session)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    assert exc.value.status_code == 403


def test_deleted_artifact_is_uniform_not_found(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, deleted=True)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 404
    assert code == PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND.value


# ── state gates ──────────────────────────────────────────────────────────────


def test_expired_artifact_is_denied(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, expired=True)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 410
    assert code == PerceptionFetchDenialCode.ARTIFACT_EXPIRED.value


@pytest.mark.parametrize("bad_status", ["not_planner_safe", "redacting"])
def test_non_planner_safe_status_is_denied(db_session, bad_status):
    _seed(db_session)
    row = _mk_artifact(
        db_session,
        status=bad_status,
        raw_deleted=False,
        write_redacted=False,
        redacted_path=None,
        write_raw=True,
    )
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_NOT_PLANNER_SAFE.value


def test_raw_not_deleted_is_denied_even_when_planner_safe(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, raw_deleted=False)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_RAW_NOT_DELETED.value


def test_desktop_control_disabled_denies_even_planner_safe_artifact(db_session):
    _seed(db_session, control_enabled=False)
    row = _mk_artifact(db_session)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 403
    assert code == PerceptionFetchDenialCode.DESKTOP_CONTROL_DISABLED.value


# ── "raw storage_path is never served" invariants ────────────────────────────


def test_db_redacted_path_pointed_at_raw_file_is_denied_not_served(db_session):
    """A tampered redacted_storage_path aimed at the RAW file must deny — the
    DB-stored path is never the filesystem authority."""
    _seed(db_session)
    row = _mk_artifact(
        db_session,
        write_redacted=False,
        write_raw=True,
        redacted_path=perception_storage.artifact_relpath(TENANT_ID, SESSION_ID, uuid.uuid4()),
    )
    # Point the stored path at this artifact's own raw file too — still denied.
    row.redacted_storage_path = str(row.storage_path)
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE.value


def test_db_redacted_path_escaping_jail_is_denied(db_session, tmp_path):
    _seed(db_session)
    outside = tmp_path / "outside.png"
    outside.write_bytes(RAW_PNG)
    row = _mk_artifact(db_session, write_redacted=False, redacted_path=str(outside))
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE.value


def test_fetch_reads_canonical_redacted_path_even_when_raw_survives(db_session):
    """Even with a (stale) raw file still on disk, the fetch returns the
    redacted bytes from the canonical id-derived path — never the raw bytes."""
    _seed(db_session)
    row = _mk_artifact(db_session, write_raw=True)
    _, data = _fetch(db_session, artifact_id=row.id)
    assert data == REDACTED_PNG
    assert b"RAW-SECRET" not in data


def test_missing_redacted_file_is_denied(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, write_redacted=False)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE.value


def test_size_mismatch_is_integrity_denied(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, size=len(REDACTED_PNG) + 1)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_INTEGRITY_MISMATCH.value


def test_sha_mismatch_is_integrity_denied(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session, sha="0" * 64)
    with pytest.raises(HTTPException) as exc:
        _fetch(db_session, artifact_id=row.id)
    status, code = _denial(exc)
    assert status == 409
    assert code == PerceptionFetchDenialCode.ARTIFACT_INTEGRITY_MISMATCH.value


# ── status projection ────────────────────────────────────────────────────────


def test_status_is_display_safe_and_reports_availability(db_session):
    _seed(db_session)
    row = _mk_artifact(db_session)
    out = perception_delivery.artifact_status(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        artifact_id=row.id,
    )
    assert out["redacted_available"] is True
    assert out["raw_deleted"] is True
    assert out["expired"] is False
    assert out["redaction_status"] == "planner_safe"
    blob = json.dumps(out)
    assert "storage_path" not in blob
    assert ".png" not in blob
    assert "RAW-SECRET" not in blob


def test_status_for_pending_artifact_reports_unavailable(db_session):
    _seed(db_session)
    row = _mk_artifact(
        db_session,
        status="not_planner_safe",
        raw_deleted=False,
        write_redacted=False,
        redacted_path=None,
    )
    out = perception_delivery.artifact_status(
        db_session,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        session_id=SESSION_ID,
        artifact_id=row.id,
    )
    assert out["redacted_available"] is False
    assert out["raw_deleted"] is False


def test_status_respects_master_flag(db_session):
    _seed(db_session, control_enabled=False)
    row = _mk_artifact(db_session)
    with pytest.raises(HTTPException) as exc:
        perception_delivery.artifact_status(
            db_session,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            session_id=SESSION_ID,
            artifact_id=row.id,
        )
    status, code = _denial(exc)
    assert status == 403
    assert code == PerceptionFetchDenialCode.DESKTOP_CONTROL_DISABLED.value


# ── thin routes ──────────────────────────────────────────────────────────────


def _client(db, user):
    app = FastAPI()
    app.include_router(desktop_control_router, prefix="/api/v1")

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app)


def test_content_route_returns_png_with_no_store_headers(db_session):
    user = _seed(db_session)
    row = _mk_artifact(db_session)
    client = _client(db_session, user)
    resp = client.get(
        f"/api/v1/desktop-control/observations/{row.id}/content",
        params={"session_id": str(SESSION_ID)},
    )
    assert resp.status_code == 200
    assert resp.content == REDACTED_PNG
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_content_route_denial_is_structured_and_display_safe(db_session):
    user = _seed(db_session)
    row = _mk_artifact(db_session, expired=True)
    client = _client(db_session, user)
    resp = client.get(
        f"/api/v1/desktop-control/observations/{row.id}/content",
        params={"session_id": str(SESSION_ID)},
    )
    assert resp.status_code == 410
    detail = resp.json()["detail"]
    assert detail["code"] == "artifact_expired"
    blob = resp.text
    assert "storage_path" not in blob
    assert ".png" not in blob


def test_status_route_returns_display_safe_projection(db_session):
    user = _seed(db_session)
    row = _mk_artifact(db_session)
    client = _client(db_session, user)
    resp = client.get(
        f"/api/v1/desktop-control/observations/{row.id}/status",
        params={"session_id": str(SESSION_ID)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["artifact_id"] == str(row.id)
    assert body["redacted_available"] is True
    assert "storage_path" not in resp.text


def test_internal_content_route_requires_internal_key(db_session):
    user = _seed(db_session)
    row = _mk_artifact(db_session)
    client = _client(db_session, user)
    resp = client.get(
        f"/api/v1/desktop-control/internal/observations/{row.id}/content",
        params={"session_id": str(SESSION_ID)},
        headers={
            "X-Internal-Key": "wrong-key",
            "X-Tenant-Id": str(TENANT_ID),
            "X-User-Id": str(USER_ID),
        },
    )
    assert resp.status_code == 401


def test_internal_content_route_delivers_base64_planner_safe_payload(db_session):
    user = _seed(db_session)
    row = _mk_artifact(db_session)
    client = _client(db_session, user)
    resp = client.get(
        f"/api/v1/desktop-control/internal/observations/{row.id}/content",
        params={"session_id": str(SESSION_ID)},
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": str(TENANT_ID),
            "X-User-Id": str(USER_ID),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert base64.b64decode(body["content_base64"]) == REDACTED_PNG
    assert body["redaction_status"] == "planner_safe"
    assert "storage_path" not in resp.text


def test_observe_request_route_records_display_safe_denial(db_session):
    user = _seed(db_session)
    client = _client(db_session, user)
    presence = {
        "active_shell": SHELL_ID,
        "connected_shells": [SHELL_ID],
        "shell_capabilities": {SHELL_ID: {"can_observe": True}},
        "shell_devices": {SHELL_ID: "88888888-8888-8888-8888-888888888888"},
    }
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=presence,
    ):
        resp = client.post(
            "/api/v1/desktop-control/observations/request",
            json={"session_id": str(SESSION_ID), "action": "capture_screenshot"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["shell_id"] == SHELL_ID
    assert body["action"] == "capture_screenshot"
    # P5.3b ships delivery, not the observe down-channel: the request records a
    # display-safe denial (down-channel unavailable) rather than capturing.
    assert body["down_channel_available"] is False

    event_source = db_session.execute(
        text("SELECT source FROM desktop_command_events ORDER BY created_at DESC LIMIT 1")
    ).scalar()
    assert event_source == "alpha"


def test_observe_request_route_denies_when_desktop_control_disabled(db_session):
    # Fail-closed: the user-facing observe-request verb re-checks the master flag,
    # so a tenant with desktop control OFF cannot drive the observe surface.
    user = _seed(db_session, control_enabled=False)
    client = _client(db_session, user)
    resp = client.post(
        "/api/v1/desktop-control/observations/request",
        json={"session_id": str(SESSION_ID), "action": "capture_screenshot"},
    )
    assert resp.status_code == 403
    # no audit event is recorded when the master gate denies
    count = db_session.execute(
        text("SELECT COUNT(*) FROM desktop_command_events")
    ).scalar()
    assert count == 0
