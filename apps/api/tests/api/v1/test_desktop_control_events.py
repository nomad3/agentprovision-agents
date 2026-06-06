from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1.desktop_control import router as desktop_control_router
from app.core.config import settings
from app.models.desktop_command import DesktopCommand
from app.models.desktop_command_event import DesktopCommandEvent
from app.services.desktop_control_service import (
    CommandAck,
    LocalObservationAudit,
    McpObservationRequest,
    ack_desktop_command,
    claim_next_desktop_command,
    record_local_observation_event,
    record_mcp_observation_request,
    stop_desktop_commands,
)

_DEFAULT_OWNER = object()
_DEVICE_REGISTRY_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
_COMMAND_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


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


def _db_with_session(found=True, owner_user_id=_DEFAULT_OWNER):
    db = MagicMock()
    if owner_user_id is _DEFAULT_OWNER:
        owner_user_id = _user().id
    db.query.return_value.filter.return_value.first.return_value = (
        SimpleNamespace(owner_user_id=owner_user_id) if found else None
    )

    def refresh(row):
        row.id = uuid.UUID("66666666-6666-6666-6666-666666666666")

    db.refresh.side_effect = refresh
    return db


def _connected_shell():
    return patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value={
            "connected_shells": ["desktop-44444444-4444-4444-4444-444444444444"],
            "shell_devices": {
                "desktop-44444444-4444-4444-4444-444444444444": str(_DEVICE_REGISTRY_ID),
            },
        },
    )


def _observable_shell_presence():
    return {
        "active_shell": "desktop-44444444-4444-4444-4444-444444444444",
        "connected_shells": ["desktop-44444444-4444-4444-4444-444444444444"],
        "shell_capabilities": {
            "desktop-44444444-4444-4444-4444-444444444444": {
                "can_observe": True,
                "can_stop": True,
                "can_control_pointer": False,
                "can_control_keyboard": False,
            },
        },
        "shell_devices": {
            "desktop-44444444-4444-4444-4444-444444444444": str(_DEVICE_REGISTRY_ID),
        },
    }


def _locked_shell_presence():
    presence = _observable_shell_presence()
    presence["shell_capabilities"]["desktop-44444444-4444-4444-4444-444444444444"][
        "can_observe"
    ] = False
    return presence


def _mcp_request(**overrides):
    values = {
        "session_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "shell_id": None,
        "action": "capture_screenshot",
        "tool_name": "desktop_observe_screen",
    }
    values.update(overrides)
    return McpObservationRequest(**values)


def _desktop_device():
    return SimpleNamespace(
        id=_DEVICE_REGISTRY_ID,
        tenant_id=_user().tenant_id,
        device_type="desktop",
        config={"shell_id": "desktop-44444444-4444-4444-4444-444444444444"},
    )


def _desktop_command(**overrides):
    values = {
        "id": _COMMAND_ID,
        "tenant_id": _user().tenant_id,
        "user_id": _user().id,
        "session_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "device_id": _DEVICE_REGISTRY_ID,
        "correlation_id": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "capability": "screenshot",
        "status": "pending",
        "source": "mcp",
        "nonce": None,
        "lease_owner_shell_id": None,
        "lease_expires_at": None,
        "claimed_at": None,
        "completed_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "payload": {"action": "capture_screenshot", "tool_name": "desktop_observe_screen"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Query:
    def __init__(self, *, first=None, all_items=None, update_count=0, update_target=None):
        self._first = first
        self._all = all_items
        self._update_count = update_count
        self._update_target = update_target

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all or []

    def update(self, values, synchronize_session=False):
        if self._update_target is not None and self._update_count:
            for key, value in values.items():
                setattr(self._update_target, getattr(key, "key", str(key)), value)
        return self._update_count


class _ScriptedDb:
    def __init__(self, queries):
        self.queries = list(queries)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args):
        if not self.queries:
            raise AssertionError("unexpected query")
        return self.queries.pop(0)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, item):
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()


def test_record_local_observation_rejects_cross_tenant_session():
    db = _db_with_session(found=False)

    with pytest.raises(HTTPException) as exc:
        record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 404
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_record_local_observation_rejects_ownerless_session():
    db = _db_with_session(found=True, owner_user_id=None)

    with pytest.raises(HTTPException) as exc:
        record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop session owner is not established"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_record_local_observation_rejects_cross_user_session():
    db = _db_with_session(
        found=True,
        owner_user_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
    )

    with pytest.raises(HTTPException) as exc:
        record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop session is not owned by user"
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


def test_record_local_observation_rejects_unbound_desktop_device():
    db = _db_with_session(found=True)

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value={"connected_shells": ["desktop-44444444-4444-4444-4444-444444444444"]},
    ):
        with pytest.raises(HTTPException) as exc:
            record_local_observation_event(db, _user(), _audit())

    assert exc.value.status_code == 409
    assert exc.value.detail == "Desktop shell device is not bound"
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
    assert persisted.device_id == _DEVICE_REGISTRY_ID
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
        "device_id": str(_DEVICE_REGISTRY_ID),
    }
    assert "screenshot" not in persisted.event_metadata
    assert "clipboard" not in persisted.event_metadata

    publish.assert_called_once()
    _, event_type, payload = publish.call_args.args
    assert event_type == "desktop_observation_denied"
    assert payload["desktop_event_id"] == "66666666-6666-6666-6666-666666666666"
    assert payload["shell_id"] == persisted.shell_id
    assert payload["device_id"] == str(_DEVICE_REGISTRY_ID)
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


def test_record_mcp_observation_request_enqueues_command_with_active_shell():
    db = _db_with_session(found=True)

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_observable_shell_presence(),
    ), patch(
        "app.services.desktop_control_service.publish_session_event",
        return_value={"event_id": "session-event-2", "seq_no": 8},
    ) as publish:
        event, session_event = record_mcp_observation_request(
            db,
            tenant_id=_user().tenant_id,
            user_id=_user().id,
            request=_mcp_request(),
        )

    command = db.add.call_args_list[0].args[0]
    assert isinstance(command, DesktopCommand)
    assert command.status == "pending"
    assert command.source == "mcp"
    assert command.payload["action"] == "capture_screenshot"
    assert command.payload["down_channel"] == {
        "available": True,
        "claim_required": True,
    }

    persisted = db.add.call_args.args[0]
    assert isinstance(persisted, DesktopCommandEvent)
    assert persisted.source == "mcp"
    assert persisted.event_type == "desktop_command_requested"
    assert persisted.action == "capture_screenshot"
    assert persisted.capability == "screenshot"
    assert persisted.outcome == "requested"
    assert persisted.mode == "observe"
    assert persisted.shell_id == "desktop-44444444-4444-4444-4444-444444444444"
    assert persisted.device_id == _DEVICE_REGISTRY_ID
    assert persisted.reason is None
    assert persisted.event_metadata["device_id"] == str(_DEVICE_REGISTRY_ID)
    assert persisted.event_metadata["down_channel"] == {
        "available": True,
    }
    assert "screenshot" not in persisted.event_metadata
    assert "clipboard" not in persisted.event_metadata
    assert event is persisted
    assert session_event == {"event_id": "session-event-2", "seq_no": 8}
    assert publish.call_args.args[1] == "desktop_command_requested"
    mirrored = publish.call_args.args[2]
    assert mirrored["status"] == "pending"
    assert mirrored["shell_id"] == persisted.shell_id
    assert mirrored["device_id"] == str(_DEVICE_REGISTRY_ID)
    assert "raw" not in mirrored
    assert "clipboard_text" not in mirrored


def test_record_mcp_observation_request_records_locked_shell_denial():
    db = _db_with_session(found=True)

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=_locked_shell_presence(),
    ), patch(
        "app.services.desktop_control_service.publish_session_event",
        return_value=None,
    ):
        record_mcp_observation_request(
            db,
            tenant_id=_user().tenant_id,
            user_id=_user().id,
            request=_mcp_request(action="read_clipboard", tool_name="desktop_read_clipboard"),
        )

    persisted = db.add.call_args.args[0]
    assert persisted.source == "mcp"
    assert persisted.action == "read_clipboard"
    assert persisted.capability == "clipboard_read"
    assert persisted.mode == "control_locked"
    assert persisted.reason == "desktop shell cannot observe; read_clipboard request denied"
    assert persisted.event_metadata["down_channel"]["reason"] == "shell_not_observable"


def test_record_mcp_observation_request_rejects_no_connected_shell():
    db = _db_with_session(found=True)

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value={"connected_shells": [], "shell_capabilities": {}},
    ):
        with pytest.raises(HTTPException) as exc:
            record_mcp_observation_request(
                db,
                tenant_id=_user().tenant_id,
                user_id=_user().id,
                request=_mcp_request(),
            )

    assert exc.value.status_code == 409
    db.add.assert_not_called()


def test_record_mcp_observation_request_rejects_unbound_desktop_device():
    db = _db_with_session(found=True)

    presence = _observable_shell_presence()
    presence["shell_devices"] = {}
    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        return_value=presence,
    ):
        with pytest.raises(HTTPException) as exc:
            record_mcp_observation_request(
                db,
                tenant_id=_user().tenant_id,
                user_id=_user().id,
                request=_mcp_request(),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Desktop shell device is not bound"
    db.add.assert_not_called()


def test_record_mcp_observation_request_rejects_user_outside_tenant():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        record_mcp_observation_request(
            db,
            tenant_id=_user().tenant_id,
            user_id=_user().id,
            request=_mcp_request(),
        )

    assert exc.value.status_code == 404
    db.add.assert_not_called()


def test_record_mcp_observation_request_rejects_ownerless_session():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        object(),  # user exists for tenant
        SimpleNamespace(owner_user_id=None),
    ]

    with pytest.raises(HTTPException) as exc:
        record_mcp_observation_request(
            db,
            tenant_id=_user().tenant_id,
            user_id=_user().id,
            request=_mcp_request(),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop session owner is not established"
    db.add.assert_not_called()


def test_record_mcp_observation_request_rejects_cross_user_session_before_shell_selection():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        object(),  # user exists for tenant
        SimpleNamespace(owner_user_id=uuid.UUID("77777777-7777-7777-7777-777777777777")),
    ]

    with patch(
        "app.services.desktop_control_service.luna_presence_service.get_presence",
        side_effect=AssertionError("shell presence should not be read before ownership passes"),
    ):
        with pytest.raises(HTTPException) as exc:
            record_mcp_observation_request(
                db,
                tenant_id=_user().tenant_id,
                user_id=_user().id,
                request=_mcp_request(),
            )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Desktop session is not owned by user"
    db.add.assert_not_called()


def test_claim_next_desktop_command_returns_none_when_cas_loses_race():
    command = _desktop_command()
    db = _ScriptedDb([
        _Query(update_count=0),  # stale lease expiry sweep
        _Query(first=command),
        _Query(update_count=0, update_target=command),  # racing claimant won
    ])

    claim = claim_next_desktop_command(
        db,
        device=_desktop_device(),
        shell_id="desktop-44444444-4444-4444-4444-444444444444",
        lease_ms=10_000,
    )

    assert claim is None
    assert command.status == "pending"
    assert db.rollbacks == 1


def test_claim_next_desktop_command_sets_short_lease_after_cas():
    command = _desktop_command()
    db = _ScriptedDb([
        _Query(update_count=0),  # stale lease expiry sweep
        _Query(first=command),
        _Query(update_count=1, update_target=command),
    ])

    with patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        claim = claim_next_desktop_command(
            db,
            device=_desktop_device(),
            shell_id="desktop-44444444-4444-4444-4444-444444444444",
            lease_ms=10_000,
        )

    assert claim is not None
    assert claim.command_id == _COMMAND_ID
    assert command.status == "claimed"
    assert command.lease_owner_shell_id == "desktop-44444444-4444-4444-4444-444444444444"
    assert command.nonce == claim.lease_id
    assert claim.lease_expires_at > datetime.now(timezone.utc)


def test_ack_desktop_command_rejects_duplicate_terminal_ack():
    command = _desktop_command(status="succeeded", nonce="lease-1")
    db = _ScriptedDb([_Query(first=command)])

    with pytest.raises(HTTPException) as exc:
        ack_desktop_command(
            db,
            device=_desktop_device(),
            shell_id="desktop-44444444-4444-4444-4444-444444444444",
            ack=CommandAck(command_id=_COMMAND_ID, lease_id="lease-1", outcome="succeeded"),
        )

    assert exc.value.status_code == 409
    assert "succeeded" in exc.value.detail


def test_ack_desktop_command_expires_stale_lease_before_execution():
    command = _desktop_command(
        status="claimed",
        nonce="lease-1",
        lease_owner_shell_id="desktop-44444444-4444-4444-4444-444444444444",
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = _ScriptedDb([_Query(first=command)])

    with pytest.raises(HTTPException) as exc:
        ack_desktop_command(
            db,
            device=_desktop_device(),
            shell_id="desktop-44444444-4444-4444-4444-444444444444",
            ack=CommandAck(command_id=_COMMAND_ID, lease_id="lease-1", outcome="running"),
        )

    assert exc.value.status_code == 409
    assert command.status == "expired"


def test_stop_preempts_pending_and_claimed_commands_before_ack():
    pending = _desktop_command(id=uuid.UUID("99999999-9999-9999-9999-999999999991"))
    claimed = _desktop_command(
        id=uuid.UUID("99999999-9999-9999-9999-999999999992"),
        status="claimed",
        nonce="lease-2",
        lease_owner_shell_id="desktop-44444444-4444-4444-4444-444444444444",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
    db = _ScriptedDb([
        _Query(all_items=[pending, claimed]),
        _Query(update_count=1, update_target=pending),
        _Query(update_count=1, update_target=claimed),
    ])

    with patch("app.services.desktop_control_service.publish_session_event", return_value=None):
        count = stop_desktop_commands(
            db,
            device=_desktop_device(),
            shell_id="desktop-44444444-4444-4444-4444-444444444444",
        )

    assert count == 2
    assert pending.status == "preempted"
    assert claimed.status == "preempted"

    ack_db = _ScriptedDb([_Query(first=claimed)])
    with pytest.raises(HTTPException) as exc:
        ack_desktop_command(
            ack_db,
            device=_desktop_device(),
            shell_id="desktop-44444444-4444-4444-4444-444444444444",
            ack=CommandAck(command_id=claimed.id, lease_id="lease-2", outcome="succeeded"),
        )

    assert exc.value.status_code == 409
    assert "preempted" in exc.value.detail


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


def test_mcp_observation_endpoint_requires_internal_user_header():
    client, _db = _client_for_endpoint(_user())
    response = client.post(
        "/api/v1/desktop-control/internal/observations/request",
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": "11111111-1111-1111-1111-111111111111",
        },
        json={
            "session_id": "33333333-3333-3333-3333-333333333333",
            "action": "capture_screenshot",
            "tool_name": "desktop_observe_screen",
        },
    )

    assert response.status_code == 400
    assert "X-User-Id required" in response.text


def test_mcp_observation_endpoint_auth_short_circuits_header_contract():
    client, _db = _client_for_endpoint(_user())
    response = client.post(
        "/api/v1/desktop-control/internal/observations/request",
        json={
            "session_id": "33333333-3333-3333-3333-333333333333",
            "action": "capture_screenshot",
            "tool_name": "desktop_observe_screen",
        },
    )

    assert response.status_code == 401
    assert "X-Tenant-Id required" not in response.text
    assert "X-User-Id required" not in response.text


def test_mcp_observation_endpoint_rejects_tool_action_mismatch():
    client, _db = _client_for_endpoint(_user())
    response = client.post(
        "/api/v1/desktop-control/internal/observations/request",
        headers={
            "X-Internal-Key": settings.API_INTERNAL_KEY,
            "X-Tenant-Id": "11111111-1111-1111-1111-111111111111",
            "X-User-Id": "22222222-2222-2222-2222-222222222222",
        },
        json={
            "session_id": "33333333-3333-3333-3333-333333333333",
            "action": "read_clipboard",
            "tool_name": "desktop_observe_screen",
        },
    )

    assert response.status_code == 422


def test_mcp_observation_endpoint_returns_display_safe_denial():
    client, _db = _client_for_endpoint(_user())
    event = MagicMock()
    event.id = uuid.UUID("66666666-6666-6666-6666-666666666666")
    event.shell_id = "desktop-44444444-4444-4444-4444-444444444444"
    event.action = "get_active_app"
    event.capability = "active_app"
    event.reason = "desktop observation down-channel unavailable; get_active_app request denied"
    event.event_metadata = {"down_channel": {"available": False, "reason": "not_implemented"}}

    with patch(
        "app.api.v1.desktop_control.record_mcp_observation_request",
        return_value=(event, {"event_id": "session-event-2", "seq_no": 8}),
    ) as record:
        response = client.post(
            "/api/v1/desktop-control/internal/observations/request",
            headers={
                "X-Internal-Key": settings.API_INTERNAL_KEY,
                "X-Tenant-Id": "11111111-1111-1111-1111-111111111111",
                "X-User-Id": "22222222-2222-2222-2222-222222222222",
            },
            json={
                "session_id": "33333333-3333-3333-3333-333333333333",
                "action": "get_active_app",
                "tool_name": "desktop_get_active_app",
            },
        )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "status": "denied",
        "desktop_event_id": "66666666-6666-6666-6666-666666666666",
        "session_event_id": "session-event-2",
        "session_seq_no": 8,
        "desktop_command_id": None,
        "shell_id": "desktop-44444444-4444-4444-4444-444444444444",
        "action": "get_active_app",
        "capability": "active_app",
        "reason": "desktop observation down-channel unavailable; get_active_app request denied",
        "down_channel_available": False,
    }
    saved_request = record.call_args.kwargs["request"]
    assert saved_request.tool_name == "desktop_get_active_app"
