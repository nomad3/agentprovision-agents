from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.desktop_control import router as desktop_control_router
from app.models.desktop_command_event import DesktopCommandEvent
from app.services.desktop_control_service import (
    LocalObservationAudit,
    record_local_observation_event,
)


def _user():
    user = MagicMock()
    user.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    user.tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    user.email = "desktop-control-test@example.test"
    return user


def _audit(**overrides):
    values = {
        "session_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "event_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
        "event_type": "desktop_observation_denied",
        "source": "tauri_local",
        "action": "capture_screenshot",
        "capability": "screenshot",
        "outcome": "denied",
        "mode": "observe",
        "created_at_ms": 1_780_000_000_000,
        "reason": "desktop observation permission 'screen_recording' is denied; capture_screenshot denied",
        "screen_recording_status": "denied",
        "accessibility_status": "denied",
        "automation_system_events_status": "unknown",
    }
    values.update(overrides)
    return LocalObservationAudit(**values)


def _db_with_session(found=True):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = object() if found else None

    def refresh(row):
        row.id = uuid.UUID("66666666-6666-6666-6666-666666666666")

    db.refresh.side_effect = refresh
    return db


def _connected_shell():
    return patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value={"connected_shells": ["desktop-44444444-4444-4444-4444-444444444444"]},
    )


def test_record_local_observation_rejects_cross_tenant_session():
    db = _db_with_session(found=False)

    with pytest.raises(HTTPException) as exc:
        record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 404
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_record_local_observation_rejects_unconnected_shell():
    db = _db_with_session(found=True)

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value={"connected_shells": []},
    ):
        with pytest.raises(HTTPException) as exc:
            record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_record_local_observation_persists_metadata_only_and_mirrors_session_event():
    db = _db_with_session(found=True)

    with _connected_shell(), patch(
        "app.services.desktop_control_service.publish_session_event",
        return_value={"event_id": "session-event-1", "seq_no": 7},
    ) as publish:
        event, session_event = record_local_observation_event(db, _user(), _audit())

    db.add.assert_called_once()
    persisted = db.add.call_args.args[0]
    assert isinstance(persisted, DesktopCommandEvent)
    assert persisted.tenant_id == _user().tenant_id
    assert persisted.user_id == _user().id
    assert persisted.session_id == _audit().session_id
    assert persisted.shell_id == "desktop-44444444-4444-4444-4444-444444444444"
    assert persisted.event_type == "desktop_observation_denied"
    assert persisted.capability == "screenshot"
    assert persisted.outcome == "denied"
    assert persisted.event_metadata == {
        "local_event_id": "55555555-5555-5555-5555-555555555555",
        "created_at_ms": 1_780_000_000_000,
        "permissions": {
            "screen_recording": "denied",
            "accessibility": "denied",
            "automation_system_events": "unknown",
        },
    }
    assert "screenshot" not in persisted.event_metadata
    assert "clipboard" not in persisted.event_metadata

    publish.assert_called_once()
    _, event_type, payload = publish.call_args.args
    assert event_type == "desktop_observation_denied"
    assert payload["desktop_event_id"] == "66666666-6666-6666-6666-666666666666"
    assert payload["shell_id"] == persisted.shell_id
    assert payload["permissions"]["screen_recording"] == "denied"
    assert "raw" not in payload
    assert "clipboard_text" not in payload
    assert session_event == {"event_id": "session-event-1", "seq_no": 7}


def test_record_local_observation_redacts_unrecognized_reason_text():
    db = _db_with_session(found=True)
    audit = _audit(
        action="read_clipboard",
        capability="clipboard_read",
        reason="raw clipboard text: customer secret",
    )

    with _connected_shell(), patch(
        "app.services.desktop_control_service.publish_session_event",
        return_value={"event_id": "session-event-1", "seq_no": 7},
    ) as publish:
        record_local_observation_event(db, _user(), audit)

    persisted = db.add.call_args.args[0]
    assert persisted.reason == "desktop observation denied"
    mirrored_payload = publish.call_args.args[2]
    assert mirrored_payload["reason"] == "desktop observation denied"
    assert "customer secret" not in str(persisted.event_metadata)
    assert "customer secret" not in str(mirrored_payload)


def test_record_local_observation_reconstructs_permission_reason_without_client_suffix():
    db = _db_with_session(found=True)
    audit = _audit(
        reason=(
            "desktop observation permission 'screen_recording' is denied; "
            "capture_screenshot denied :: customer secret"
        ),
    )

    with _connected_shell(), patch(
        "app.services.desktop_control_service.publish_session_event",
        return_value={"event_id": "session-event-1", "seq_no": 7},
    ) as publish:
        record_local_observation_event(db, _user(), audit)

    persisted = db.add.call_args.args[0]
    expected = "desktop observation permission 'screen_recording' is denied; capture_screenshot denied"
    assert persisted.reason == expected
    assert publish.call_args.args[2]["reason"] == expected
    assert "customer secret" not in persisted.reason
    assert "customer secret" not in str(publish.call_args.args[2])


def _client_for_endpoint(user):
    app = FastAPI()
    app.include_router(desktop_control_router, prefix="/api/v1")
    db = MagicMock()

    def _fake_db():
        yield db

    app.dependency_overrides[deps.get_db] = _fake_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    return TestClient(app), db


def test_local_observation_endpoint_rejects_unknown_raw_payload_fields():
    client, _db = _client_for_endpoint(_user())
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "event_id": "55555555-5555-5555-5555-555555555555",
        "event_type": "desktop_observation_denied",
        "source": "tauri_local",
        "action": "read_clipboard",
        "capability": "clipboard_read",
        "outcome": "denied",
        "mode": "observe",
        "raw_clipboard_text": "do not store me",
    }

    response = client.post("/api/v1/desktop-control/events/local-observation", json=payload)

    assert response.status_code == 422


def test_local_observation_endpoint_rejects_non_uuid_event_id():
    client, _db = _client_for_endpoint(_user())
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "event_id": "raw-clipboard-smuggle",
        "event_type": "desktop_observation_denied",
        "source": "tauri_local",
        "action": "read_clipboard",
        "capability": "clipboard_read",
        "outcome": "denied",
        "mode": "observe",
    }

    response = client.post("/api/v1/desktop-control/events/local-observation", json=payload)

    assert response.status_code == 422


def test_local_observation_endpoint_returns_event_ids():
    client, _db = _client_for_endpoint(_user())
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "event_id": "55555555-5555-5555-5555-555555555555",
        "event_type": "desktop_observation_denied",
        "source": "tauri_local",
        "action": "capture_screenshot",
        "capability": "screenshot",
        "outcome": "denied",
        "mode": "observe",
        "screen_recording_status": "denied",
    }
    event = MagicMock()
    event.id = uuid.UUID("66666666-6666-6666-6666-666666666666")

    with patch(
        "app.api.v1.desktop_control.record_local_observation_event",
        return_value=(event, {"event_id": "session-event-1", "seq_no": 7}),
    ):
        response = client.post("/api/v1/desktop-control/events/local-observation", json=payload)

    assert response.status_code == 201, response.text
    assert response.json() == {
        "desktop_event_id": "66666666-6666-6666-6666-666666666666",
        "session_event_id": "session-event-1",
        "session_seq_no": 7,
    }
