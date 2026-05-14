"""Tests for `POST /api/v1/claude-auth/submit-code` and the underlying
`ClaudeAuthManager.submit_code` (PR #471, option b — stdin-forward).

Coverage:
  * Happy path: state transitions `pending → submitting`; stdin write
    + flush + close in the right order; `_code_submitted` event fired.
  * Domain errors translate to HTTP: no-state → 404, wrong-state → 400,
    dead-subprocess → 400, empty-code → 400.
  * Cancel-vs-submit race (B2): when both fire concurrently, the
    terminal state is deterministic (one wins, the other no-ops or
    errors cleanly — no `submitting` after `cancelled`).
  * Domain-level error class: manager.submit_code raises
    `ClaudeAuthError` (not `HTTPException`), keeping it usable from
    non-HTTP callers.
"""

from __future__ import annotations

import threading
import time
import uuid
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import claude_auth as ca


def _fake_user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.uuid4()
    u.is_active = True
    u.email = "claude-submit-code-test@example.test"
    return u


def _make_client(user, *, monkeypatch):
    app = FastAPI()
    app.include_router(ca.router, prefix="/api/v1/claude-auth")
    app.dependency_overrides[deps.get_db] = lambda: iter([MagicMock()])
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    # The /submit-code route calls _tenant_has_claude_credential which
    # queries the DB; stub it so we don't need a real session.
    monkeypatch.setattr(ca, "_tenant_has_claude_credential", lambda db, tid: False)
    return TestClient(app)


def _make_pending_state(tenant_id: str, *, alive: bool = True):
    """Build a ClaudeLoginState in `pending` with a fake live subprocess.

    Mocks stdin so writes are captured for assertions and don't try to
    talk to a real process. Mocks `process.poll()` so the state-machine
    guards pass.
    """
    state = ca.ClaudeLoginState(
        login_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        status="pending",
        verification_url="https://claude.com/login/device?code=abc",
    )
    proc = MagicMock()
    proc.poll.return_value = None if alive else 0
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.flush = MagicMock()
    proc.stdin.close = MagicMock()
    state.process = proc
    return state, proc


# ── Manager: submit_code domain layer ────────────────────────────────────

def test_submit_code_happy_path_writes_to_stdin_and_signals_event():
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-happy")
    mgr._by_tenant["tenant-happy"] = state

    out = mgr.submit_code("tenant-happy", "verification-code-XYZ")

    assert out.status == "submitting"
    assert state._code_submitted.is_set()
    proc.stdin.write.assert_called_once_with("verification-code-XYZ\n")
    proc.stdin.flush.assert_called_once()
    proc.stdin.close.assert_called_once()


def test_submit_code_strips_wrapping_quotes_and_whitespace():
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-quotes")
    mgr._by_tenant["tenant-quotes"] = state

    mgr.submit_code("tenant-quotes", '  "code-abc"  ')

    # Stripped paste artefacts — stdin sees the clean code only.
    proc.stdin.write.assert_called_once_with("code-abc\n")


def test_submit_code_raises_domain_error_not_http_exception():
    """The manager must NOT raise HTTPException — that's the route's
    job. Keeps the manager usable from CLI tools and tests without a
    FastAPI app."""
    mgr = ca.ClaudeAuthManager()

    with pytest.raises(ca.ClaudeAuthError) as exc:
        mgr.submit_code("tenant-missing", "code")
    assert exc.value.status_code == 404


def test_submit_code_rejects_wrong_state():
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state("tenant-wrong-state")
    state.status = "cancelled"
    mgr._by_tenant["tenant-wrong-state"] = state

    with pytest.raises(ca.ClaudeAuthError) as exc:
        mgr.submit_code("tenant-wrong-state", "code")
    assert exc.value.status_code == 400
    assert "cancelled" in exc.value.detail


def test_submit_code_rejects_dead_subprocess():
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state("tenant-dead", alive=False)
    mgr._by_tenant["tenant-dead"] = state

    with pytest.raises(ca.ClaudeAuthError) as exc:
        mgr.submit_code("tenant-dead", "code")
    assert exc.value.status_code == 400
    assert "no longer running" in exc.value.detail


def test_submit_code_rejects_empty_code():
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state("tenant-empty")
    mgr._by_tenant["tenant-empty"] = state

    with pytest.raises(ca.ClaudeAuthError):
        mgr.submit_code("tenant-empty", "   ")


def test_submit_code_handles_broken_pipe():
    """Subprocess died between status check and write — surface as 400
    with the 'Re-run /start' hint."""
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-broken")
    mgr._by_tenant["tenant-broken"] = state
    proc.stdin.write.side_effect = BrokenPipeError("child gone")

    with pytest.raises(ca.ClaudeAuthError) as exc:
        mgr.submit_code("tenant-broken", "code-abc")
    assert exc.value.status_code == 400
    assert "Re-run" in exc.value.detail


# ── Cancel-vs-submit race (B2 regression guard) ──────────────────────────

def test_cancel_during_submit_does_not_leave_submitting_status():
    """Run cancel + submit concurrently and assert the terminal state
    is deterministic.

    Two valid outcomes (depending on which thread acquires the lock
    first):

      a) submit wins → final state == 'submitting', submit returns ok,
         cancel observes 'submitting' (NOT in {starting, pending}) and
         no-ops without mutating.

      b) cancel wins → final state == 'cancelled', submit observes
         'cancelled' and raises ClaudeAuthError.

    What MUST NOT happen:
      * submit succeeds AND state ends 'cancelled' — would mean stdin
        was written to a subprocess that's then terminated, with the
        UI reporting cancellation even though the OAuth handshake may
        have already started server-side.
    """
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-race")
    mgr._by_tenant["tenant-race"] = state

    results = {}

    def do_submit():
        try:
            mgr.submit_code("tenant-race", "code-race")
            results["submit"] = "ok"
        except ca.ClaudeAuthError as exc:
            results["submit"] = f"error:{exc.detail}"

    def do_cancel():
        mgr.cancel_login("tenant-race")
        results["cancel"] = "ok"

    t1 = threading.Thread(target=do_submit)
    t2 = threading.Thread(target=do_cancel)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # One of two valid final states. Anything else is a race bug.
    assert state.status in ("submitting", "cancelled"), (
        f"Race produced bad final state: {state.status}"
    )
    # The forbidden combination: submit succeeded but state landed
    # 'cancelled' — the bug the cancel-guard prevents.
    if state.status == "cancelled":
        assert results.get("submit", "").startswith("error:"), (
            "Cancel won the race but submit succeeded — status was overwritten "
            "after data was already written to subprocess stdin"
        )
    elif state.status == "submitting":
        # Submit won. Cancel must have observed `submitting` and returned
        # without raising (no-op on non-cancellable state).
        assert results.get("cancel") == "ok"
        assert results.get("submit") == "ok"


def test_cancel_is_noop_when_state_is_submitting():
    """Direct (non-race) test of the cancel-guard: once status is
    `submitting`, cancel does not overwrite it."""
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state("tenant-noop")
    state.status = "submitting"
    mgr._by_tenant["tenant-noop"] = state

    out = mgr.cancel_login("tenant-noop")

    assert out is state  # returns the state, not None
    assert state.status == "submitting", "cancel must not overwrite submitting"
    assert state.error is None  # error field should not be set either


def test_cancel_is_noop_when_state_is_connected():
    """cancel on a terminal state is a no-op."""
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state("tenant-connected")
    state.status = "connected"
    state.connected = True
    mgr._by_tenant["tenant-connected"] = state

    mgr.cancel_login("tenant-connected")

    assert state.status == "connected"
    assert state.connected is True


def test_cancel_succeeds_from_pending():
    """The happy path: cancel of an in-flight pending login transitions
    to cancelled and reaps the subprocess."""
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-cancel-pending")
    mgr._by_tenant["tenant-cancel-pending"] = state

    mgr.cancel_login("tenant-cancel-pending")

    assert state.status == "cancelled"
    assert state.error == "Login cancelled"
    proc.terminate.assert_called_once()


def test_cancel_then_submit_returns_400():
    """The other race direction: cancel runs first, then submit
    arrives. Submit must observe 'cancelled' and raise, never write
    to stdin."""
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-cancel-then-submit")
    mgr._by_tenant["tenant-cancel-then-submit"] = state

    mgr.cancel_login("tenant-cancel-then-submit")
    assert state.status == "cancelled"

    with pytest.raises(ca.ClaudeAuthError) as exc:
        mgr.submit_code("tenant-cancel-then-submit", "code-late")

    assert exc.value.status_code == 400
    assert "cancelled" in exc.value.detail
    # Crucially, stdin must NOT have been written.
    proc.stdin.write.assert_not_called()


def test_cancel_releases_lock_before_terminating_subprocess(monkeypatch):
    """`cancel_login` must do its status mutation under the lock and
    release before calling terminate, so concurrent `/status` polling
    isn't blocked behind the SIGTERM grace period."""
    mgr = ca.ClaudeAuthManager()
    state, proc = _make_pending_state("tenant-release")
    mgr._by_tenant["tenant-release"] = state

    terminate_called = threading.Event()
    can_finish_terminate = threading.Event()

    def fake_terminate_and_reap(p):
        terminate_called.set()
        # Hold up the terminate path; meanwhile `get_state` should
        # still be able to acquire the lock and read state.
        can_finish_terminate.wait(timeout=2)

    monkeypatch.setattr(ca, "_terminate_and_reap", fake_terminate_and_reap)

    cancel_thread = threading.Thread(target=lambda: mgr.cancel_login("tenant-release"))
    cancel_thread.start()
    # Wait until cancel is mid-terminate.
    assert terminate_called.wait(timeout=2), "cancel_login never reached terminate"

    # Lock should already be released — get_state must not block.
    poll_start = time.monotonic()
    polled_state = mgr.get_state("tenant-release")
    poll_duration = time.monotonic() - poll_start
    assert polled_state is not None
    assert polled_state.status == "cancelled"
    assert poll_duration < 0.5, f"get_state blocked behind terminate: {poll_duration}s"

    can_finish_terminate.set()
    cancel_thread.join(timeout=2)


# ── /submit-code route translation ───────────────────────────────────────

def test_route_translates_domain_error_404(monkeypatch):
    user = _fake_user()
    # No state registered for this tenant — manager raises ClaudeAuthError(404).
    monkeypatch.setattr(ca, "_manager", ca.ClaudeAuthManager())
    client = _make_client(user, monkeypatch=monkeypatch)

    resp = client.post("/api/v1/claude-auth/submit-code", json={"code": "abc12345"})
    assert resp.status_code == 404
    assert "No active Claude login flow" in resp.json()["detail"]


def test_route_translates_domain_error_400(monkeypatch):
    user = _fake_user()
    mgr = ca.ClaudeAuthManager()
    state, _ = _make_pending_state(str(user.tenant_id), alive=False)
    mgr._by_tenant[str(user.tenant_id)] = state
    monkeypatch.setattr(ca, "_manager", mgr)
    client = _make_client(user, monkeypatch=monkeypatch)

    resp = client.post("/api/v1/claude-auth/submit-code", json={"code": "abc12345"})
    assert resp.status_code == 400
    assert "no longer running" in resp.json()["detail"]


def test_route_min_length_validation(monkeypatch):
    """Pydantic `min_length=4` rejects obvious typos before we even
    reach the manager. Boundary: 3 chars → 422, 4 chars passes
    pydantic (then hits manager state check)."""
    user = _fake_user()
    monkeypatch.setattr(ca, "_manager", ca.ClaudeAuthManager())
    client = _make_client(user, monkeypatch=monkeypatch)

    too_short = client.post("/api/v1/claude-auth/submit-code", json={"code": "xyz"})
    assert too_short.status_code == 422

    just_long_enough = client.post("/api/v1/claude-auth/submit-code", json={"code": "xyzw"})
    # Passes pydantic, fails manager (no state) → 404.
    assert just_long_enough.status_code == 404


# ── CLI-error humanisation (I3) ──────────────────────────────────────────

def test_humanise_cli_failure_maps_expiry_to_friendly_message():
    raw = "\x1b[31mError: invalid_grant — code expired\x1b[0m"
    out = ca._humanise_cli_failure(raw)
    assert "expired" in out.lower()
    assert "Click Connect" in out  # friendly message, not the raw dump


def test_humanise_cli_failure_falls_back_to_raw_for_unknown():
    raw = "Network unreachable: ENETUNREACH"
    out = ca._humanise_cli_failure(raw)
    # Unknown error → return the raw (truncated) so we don't swallow it.
    assert "ENETUNREACH" in out


def test_humanise_cli_failure_truncates_to_500_chars():
    raw = "x" * 2000
    out = ca._humanise_cli_failure(raw)
    assert len(out) <= 500


def test_humanise_cli_failure_handles_empty_input():
    assert ca._humanise_cli_failure("") == "Claude authorization failed"


def test_humanise_cli_failure_no_false_positive_on_not_expired():
    """The hint list must not contain bare `expired` because benign
    output like 'certificate has not expired' would false-positive
    into the friendly-message branch. Lock this contract in."""
    benign_outputs = [
        "TLS certificate has not expired",
        "session token will be expired tomorrow",
        "Error: TLS certificate not yet expired",
    ]
    for raw in benign_outputs:
        out = ca._humanise_cli_failure(raw)
        assert "Click Connect" not in out, (
            f"False-positive expiry match on benign output: {raw!r}"
        )


# ── _snapshot_buf (I1 race guard) ────────────────────────────────────────

def test_snapshot_buf_handles_concurrent_appends():
    """The snapshot must not raise even if the reader thread appends
    concurrently. We don't assert content (race makes it
    non-deterministic), only that no exception escapes."""
    buf = []

    def writer():
        for i in range(1000):
            buf.append(f"line-{i}\n")

    w = threading.Thread(target=writer, daemon=True)
    w.start()
    for _ in range(50):
        # Repeatedly snapshot while writer is mutating.
        out = ca._snapshot_buf(buf)
        assert isinstance(out, str)
    w.join(timeout=2)


# ── _terminate_and_reap (I2 zombie guard) ────────────────────────────────

def test_terminate_and_reap_noop_on_dead_process():
    proc = MagicMock()
    proc.poll.return_value = 0  # already exited
    ca._terminate_and_reap(proc)
    proc.terminate.assert_not_called()


def test_terminate_and_reap_escalates_to_kill_on_timeout():
    import subprocess
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired("c", 5), 0]

    ca._terminate_and_reap(proc)

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


def test_terminate_and_reap_no_kill_on_graceful_exit():
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0  # exits within grace period

    ca._terminate_and_reap(proc)

    proc.terminate.assert_called_once()
    proc.kill.assert_not_called()
