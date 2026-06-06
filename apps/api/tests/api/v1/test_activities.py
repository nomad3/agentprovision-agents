from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.activities import (
    MACOS_APP_MONITOR_EVENT_SCHEMA,
    ActivityTrackRequest,
    track_activity,
)


def _user():
    return SimpleNamespace(
        id=uuid.UUID("22222222-2222-4222-8222-222222222222"),
        tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )


def _tracked_row(db: MagicMock):
    return db.add.call_args.args[0]


def test_track_activity_strips_raw_native_monitor_content_from_storage():
    db = MagicMock()
    body = ActivityTrackRequest(
        schema=MACOS_APP_MONITOR_EVENT_SCHEMA,
        event_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        type="app_switch",
        source_shell="desktop-33333333-3333-4333-8333-333333333333",
        from_app="Code",
        to_app="Terminal",
        window_title="secret repo window title",
        subprocess={"active_processes": [{"args": "secret args"}]},
        duration_secs=3,
        timestamp=123,
        observed_at_ms=123000,
        active_context_id="Terminal:ABC123",
        detail_level="raw",
        monitor_source="untrusted source",
        window_title_present=True,
        window_title_chars=24,
    )

    result = track_activity(body, db=db, current_user=_user())

    assert result == {"status": "ok"}
    row = _tracked_row(db)
    assert row.window_title is None
    assert row.app_name == "Terminal"
    assert row.detail == {
        "type": "app_switch",
        "schema": MACOS_APP_MONITOR_EVENT_SCHEMA,
        "event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "source_shell": "desktop-33333333-3333-4333-8333-333333333333",
        "from_app": "Code",
        "to_app": "Terminal",
        "duration_secs": 3.0,
        "timestamp": 123,
        "observed_at_ms": 123000,
        "active_context_id": "Terminal:abc123",
        "detail_level": "metadata_only",
        "monitor_source": "tauri_activity_tracker",
        "window_title_present": True,
        "window_title_chars": 24,
    }
    assert "secret repo window title" not in str(row.detail)
    assert "secret args" not in str(row.detail)
    db.commit.assert_called_once()


def test_track_activity_does_not_promote_legacy_app_switch_to_v1():
    db = MagicMock()
    body = ActivityTrackRequest(
        type="app_switch",
        source_shell="desktop-33333333-3333-4333-8333-333333333333",
        from_app="Code",
        to_app="Terminal",
        window_title="secret repo window title",
        subprocess={"active_processes": [{"args": "secret args"}]},
        duration_secs=3,
        timestamp=123,
    )

    track_activity(body, db=db, current_user=_user())

    row = _tracked_row(db)
    assert row.window_title is None
    assert row.detail == {
        "type": "app_switch",
        "detail_level": "metadata_only",
        "source_shell": "desktop-33333333-3333-4333-8333-333333333333",
        "from_app": "Code",
        "to_app": "Terminal",
        "duration_secs": 3.0,
        "timestamp": 123,
    }
    assert "schema" not in row.detail
    assert "window_title" not in row.detail
    assert "subprocess" not in row.detail


def test_track_activity_rejects_v1_monitor_event_without_uuid_event_id():
    db = MagicMock()
    body = ActivityTrackRequest(
        schema=MACOS_APP_MONITOR_EVENT_SCHEMA,
        event_id="secret repo title",
        type="app_switch",
        to_app="Terminal",
    )

    with pytest.raises(HTTPException) as exc:
        track_activity(body, db=db, current_user=_user())

    assert exc.value.status_code == 422
    assert "event_id" in exc.value.detail
    db.add.assert_not_called()
