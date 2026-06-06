from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.devices import router as devices_router
from app.api.v1.presence import router as presence_router
from app.models.device_registry import DeviceRegistry


def _user():
    return SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )


def _client(router, user=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    db = MagicMock()

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_user] = lambda: user or _user()
    app.dependency_overrides[deps.get_current_active_user] = lambda: user or _user()
    return TestClient(app), db


def test_desktop_device_enrollment_creates_bound_device_and_returns_claim_token():
    client, db = _client(devices_router)
    db.query.return_value.filter.return_value.first.return_value = None

    def refresh(row):
        row.id = uuid.UUID("88888888-8888-8888-8888-888888888888")

    db.refresh.side_effect = refresh

    response = client.post(
        "/api/v1/devices/desktop/enroll",
        json={
            "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
            "capabilities": {
                "can_observe": True,
                "can_control_pointer": False,
                "ignored": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == "88888888-8888-8888-8888-888888888888"
    assert body["device_id"] == (
        "11111111-1111-1111-1111-111111111111-"
        "desktop-44444444-4444-4444-4444-444444444444"
    )
    assert body["device_token"]
    assert body["shell_id"] == "desktop-44444444-4444-4444-4444-444444444444"

    db.add.assert_called_once()
    persisted = db.add.call_args.args[0]
    assert isinstance(persisted, DeviceRegistry)
    assert persisted.device_type == "desktop"
    assert persisted.status == "online"
    assert persisted.capabilities == ["can_observe"]
    assert persisted.config["shell_id"] == "desktop-44444444-4444-4444-4444-444444444444"
    assert "ignored" in persisted.config["capability_manifest"]


def test_desktop_device_enrollment_rejects_non_desktop_shell_id():
    client, db = _client(devices_router)

    response = client.post(
        "/api/v1/devices/desktop/enroll",
        json={"shell_id": "web", "capabilities": {"can_observe": True}},
    )

    assert response.status_code == 422
    db.add.assert_not_called()


def test_shell_register_binds_authenticated_desktop_device_to_presence():
    client, db = _client(presence_router)
    device = SimpleNamespace(
        id=uuid.UUID("88888888-8888-8888-8888-888888888888"),
        config={"shell_id": "desktop-44444444-4444-4444-4444-444444444444"},
        status="offline",
        last_heartbeat=None,
        updated_at=None,
    )
    db.query.return_value.filter.return_value.first.return_value = device

    with patch("app.api.v1.presence.luna_presence_service.register_shell") as register:
        register.return_value = {"connected_shells": ["desktop-44444444-4444-4444-4444-444444444444"]}
        response = client.post(
            "/api/v1/presence/shell/register",
            headers={"X-Device-Token": "secret-token"},
            json={
                "shell": "desktop-44444444-4444-4444-4444-444444444444",
                "device_id": (
                    "11111111-1111-1111-1111-111111111111-"
                    "desktop-44444444-4444-4444-4444-444444444444"
                ),
                "capabilities": {"can_observe": True},
            },
        )

    assert response.status_code == 200, response.text
    db.commit.assert_called_once()
    assert device.status == "online"
    register.assert_called_once_with(
        _user().tenant_id,
        "desktop-44444444-4444-4444-4444-444444444444",
        capabilities={"can_observe": True},
        device_registry_id="88888888-8888-8888-8888-888888888888",
        device_id=(
            "11111111-1111-1111-1111-111111111111-"
            "desktop-44444444-4444-4444-4444-444444444444"
        ),
    )


def test_shell_register_requires_device_token_when_device_id_is_supplied():
    client, db = _client(presence_router)

    response = client.post(
        "/api/v1/presence/shell/register",
        json={
            "shell": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": (
                "11111111-1111-1111-1111-111111111111-"
                "desktop-44444444-4444-4444-4444-444444444444"
            ),
        },
    )

    assert response.status_code == 401
    db.query.assert_not_called()


def test_shell_register_rejects_unknown_or_cross_tenant_device_token():
    client, db = _client(presence_router)
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.api.v1.presence.luna_presence_service.register_shell") as register:
        response = client.post(
            "/api/v1/presence/shell/register",
            headers={"X-Device-Token": "wrong-token"},
            json={
                "shell": "desktop-44444444-4444-4444-4444-444444444444",
                "device_id": (
                    "11111111-1111-1111-1111-111111111111-"
                    "desktop-44444444-4444-4444-4444-444444444444"
                ),
            },
        )

    assert response.status_code == 401
    register.assert_not_called()


def test_shell_register_rejects_device_token_shell_mismatch():
    client, db = _client(presence_router)
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=uuid.UUID("88888888-8888-8888-8888-888888888888"),
        config={"shell_id": "desktop-99999999-9999-9999-9999-999999999999"},
    )

    response = client.post(
        "/api/v1/presence/shell/register",
        headers={"X-Device-Token": "secret-token"},
        json={
            "shell": "desktop-44444444-4444-4444-4444-444444444444",
            "device_id": (
                "11111111-1111-1111-1111-111111111111-"
                "desktop-44444444-4444-4444-4444-444444444444"
            ),
        },
    )

    assert response.status_code == 403
