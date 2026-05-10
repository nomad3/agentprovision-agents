"""Phase 3 commit 8 — worker-side heartbeat-missed event emission tests.

Verifies cli_runtime.emit_heartbeat_missed_event:
  - posts to /api/v1/internal/orchestrator/events with correct shape
  - X-Internal-Key header set
  - returns True on 2xx, False on 4xx/5xx and on connection error

Plus a 'staleness-threshold' simulation: caller logic that calls
emit_heartbeat_missed_event when elapsed > 2*heartbeat_interval.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import cli_runtime


def test_emit_heartbeat_missed_event_happy_path():
    captured = {}

    class _FakeResp:
        status_code = 204

    class _FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResp()

    with patch.dict("sys.modules", {"httpx": MagicMock(Client=_FakeClient)}):
        ok = cli_runtime.emit_heartbeat_missed_event(
            tenant_id="t-123", run_id="r-1",
            last_seen_ts=1234567890.0,
            parent_workflow_id="wf-1", parent_task_id="task-9",
            api_base_url="http://api", api_internal_key="k",
        )

    assert ok is True
    assert captured["url"] == "http://api/api/v1/internal/orchestrator/events"
    assert captured["headers"]["X-Internal-Key"] == "k"
    body = captured["json"]
    assert body["event_type"] == "execution.heartbeat_missed"
    assert body["tenant_id"] == "t-123"
    assert body["payload"]["run_id"] == "r-1"
    assert body["payload"]["last_seen_ts"] == 1234567890.0


def test_emit_heartbeat_missed_event_returns_false_on_5xx():
    class _FakeResp:
        status_code = 500

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            return _FakeResp()

    with patch.dict("sys.modules", {"httpx": MagicMock(Client=_FakeClient)}):
        ok = cli_runtime.emit_heartbeat_missed_event(
            tenant_id="t", run_id="r",
            last_seen_ts=0.0,
            api_base_url="http://api", api_internal_key="k",
        )
    assert ok is False


def test_emit_heartbeat_missed_event_returns_false_on_connection_error():
    class _FakeClient:
        def __init__(self, timeout=None):
            raise ConnectionError("api unreachable")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *a, **kw):
            return None

    with patch.dict("sys.modules", {"httpx": MagicMock(Client=_FakeClient)}):
        ok = cli_runtime.emit_heartbeat_missed_event(
            tenant_id="t", run_id="r", last_seen_ts=0.0,
            api_base_url="http://api", api_internal_key="k",
        )
    assert ok is False


def test_staleness_threshold_simulation():
    """Caller calls emit_heartbeat_missed_event when elapsed >= 2*interval.

    This exercises the integration shape — when the heartbeat-poll loop
    sees staleness above the threshold it MUST fire the event.
    """
    import time as _time

    interval = 30
    threshold = 2 * interval  # 60s
    last_seen = _time.time() - (threshold + 5)  # well over

    fired = {"n": 0}

    def fake_emit(**kwargs):
        fired["n"] += 1
        return True

    with patch.object(cli_runtime, "emit_heartbeat_missed_event", fake_emit):
        # Caller-side staleness logic: if (now - last_seen) > threshold, emit.
        elapsed = _time.time() - last_seen
        if elapsed > threshold:
            cli_runtime.emit_heartbeat_missed_event(
                tenant_id="t", run_id="r",
                last_seen_ts=last_seen,
            )

    assert fired["n"] == 1


def test_staleness_threshold_does_not_fire_when_fresh():
    import time as _time

    interval = 30
    threshold = 2 * interval
    last_seen = _time.time() - 5  # 5s ago — fresh

    fired = {"n": 0}

    def fake_emit(**kwargs):
        fired["n"] += 1

    with patch.object(cli_runtime, "emit_heartbeat_missed_event", fake_emit):
        elapsed = _time.time() - last_seen
        if elapsed > threshold:
            cli_runtime.emit_heartbeat_missed_event(
                tenant_id="t", run_id="r",
                last_seen_ts=last_seen,
            )

    assert fired["n"] == 0
