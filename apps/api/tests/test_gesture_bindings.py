"""Tests for gesture binding schemas, service, and API endpoints."""
import os
import uuid

os.environ.setdefault("TESTING", "True")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_db
from app.db.base import Base
from app.db.session import SessionLocal, engine

from app.schemas.gesture_binding import (
    ActionKind,
    ActionSpec,
    Binding,
    BindingsPayload,
    GestureSpec,
    Pose,
)


def _override_get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    yield SessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="auth_headers")
def auth_headers_fixture(db_session):
    email = f"gesture-{uuid.uuid4().hex[:8]}@example.com"
    pw = "testpassword"
    client.post(
        "/api/v1/auth/register",
        json={
            "user_in": {"email": email, "password": pw, "full_name": "Gesture User"},
            "tenant_in": {"name": "Gesture Tenant"},
        },
    )
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": pw},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Schema validation ──────────────────────────────────────────────────────

def test_binding_rejects_unknown_action_kind():
    with pytest.raises(Exception):
        Binding(
            id="b1",
            gesture=GestureSpec(pose=Pose.OPEN_PALM),
            action={"kind": "definitely_not_real"},  # type: ignore[arg-type]
            scope="global",
            enabled=True,
            user_recorded=False,
        )


def test_binding_accepts_valid_payload():
    payload = BindingsPayload(bindings=[
        Binding(
            id="b1",
            gesture=GestureSpec(pose=Pose.OPEN_PALM),
            action=ActionSpec(kind=ActionKind.NAV_HUD),
            scope="global",
        )
    ])
    assert len(payload.bindings) == 1
    assert payload.bindings[0].action.kind == ActionKind.NAV_HUD


def test_binding_rejects_too_many():
    with pytest.raises(Exception):
        BindingsPayload(bindings=[
            Binding(
                id=f"b{i}",
                gesture=GestureSpec(pose=Pose.OPEN_PALM),
                action=ActionSpec(kind=ActionKind.NAV_HUD),
                scope="global",
            )
            for i in range(101)
        ])


# ── Service round-trip ────────────────────────────────────────────────────

def test_service_round_trip(db_session, auth_headers):
    # auth_headers fixture creates a user; pull them via /me to get IDs.
    me = client.get("/api/v1/users/me", headers=auth_headers).json()
    tenant_id = uuid.UUID(me["tenant_id"]) if "tenant_id" in me else uuid.UUID(me.get("tenant", {}).get("id"))
    user_id = uuid.UUID(me["id"])

    from app.services.gesture_bindings_service import (
        get_bindings_for_user,
        save_bindings_for_user,
    )

    serialized = [
        Binding(
            id="b1",
            gesture=GestureSpec(pose=Pose.OPEN_PALM),
            action=ActionSpec(kind=ActionKind.NAV_HUD),
            scope="global",
        ).model_dump(mode="json")
    ]
    save_bindings_for_user(db_session, tenant_id, user_id, serialized)
    db_session.commit()
    loaded = get_bindings_for_user(db_session, tenant_id, user_id)
    assert len(loaded) == 1
    assert loaded[0]["action"]["kind"] == "nav_hud"


# ── Endpoint behavior ─────────────────────────────────────────────────────

def test_get_bindings_default_empty(db_session, auth_headers):
    r = client.get("/api/v1/users/me/gesture-bindings", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["bindings"] == []
    assert body["updated_at"] is None


def test_put_then_get_bindings(db_session, auth_headers):
    payload = {
        "bindings": [
            {
                "id": "b1",
                "gesture": {"pose": "open_palm"},
                "action": {"kind": "nav_hud"},
                "scope": "global",
                "enabled": True,
                "user_recorded": False,
            }
        ]
    }
    put = client.put(
        "/api/v1/users/me/gesture-bindings",
        json=payload,
        headers=auth_headers,
    )
    assert put.status_code == 204

    got = client.get("/api/v1/users/me/gesture-bindings", headers=auth_headers).json()
    assert len(got["bindings"]) == 1
    assert got["bindings"][0]["action"]["kind"] == "nav_hud"
    assert got["updated_at"] is not None


def test_put_rejects_unknown_action_via_pydantic(db_session, auth_headers):
    payload = {
        "bindings": [
            {
                "id": "b1",
                "gesture": {"pose": "open_palm"},
                "action": {"kind": "totally_invalid"},
                "scope": "global",
                "enabled": True,
                "user_recorded": False,
            }
        ]
    }
    r = client.put(
        "/api/v1/users/me/gesture-bindings",
        json=payload,
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_put_rejects_oversize(db_session, auth_headers):
    huge = "x" * 70_000
    payload = {
        "bindings": [
            {
                "id": "b1",
                "gesture": {"pose": "open_palm"},
                "action": {"kind": "mcp_tool", "params": {"blob": huge}},
                "scope": "global",
                "enabled": True,
                "user_recorded": False,
            }
        ]
    }
    r = client.put(
        "/api/v1/users/me/gesture-bindings",
        json=payload,
        headers=auth_headers,
    )
    assert r.status_code in (413, 422)
