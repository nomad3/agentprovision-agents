"""Tests for the streaming line-reader path in `cli_runtime.run_cli_with_heartbeat`.

The previous impl used `proc.communicate()` and buffered everything to
end-of-run. The new impl spawns two drain threads and fires `on_chunk`
per line. These tests verify:

  - Two prints separated by a sleep fire on_chunk twice, in order.
  - Timeout-kill path still raises subprocess.TimeoutExpired.
  - stdout vs stderr chunks land with the right fd label.

Uses real `python -c '...'` subprocesses (no mock subprocess module).
"""
from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

import cli_runtime


# Temporal's `activity.heartbeat()` raises outside an activity context.
# Patch it to a no-op so the runtime helper can run under plain pytest.
@pytest.fixture(autouse=True)
def _stub_activity_heartbeat():
    with patch.object(cli_runtime, "activity") as fake:
        fake.heartbeat = lambda *_a, **_k: None
        yield


def test_on_chunk_fires_per_line_in_order():
    """Two prints with a sleep between them → on_chunk fires twice in order."""
    captured: list[tuple[str, str]] = []

    def on_chunk(line, fd):
        captured.append((fd, line.rstrip("\n")))

    # `-u` for unbuffered stdout; otherwise Python may batch the two
    # prints into one EOF flush and the test passes trivially.
    cmd = [sys.executable, "-u", "-c",
           "import sys, time; print('first'); sys.stdout.flush(); time.sleep(0.1); print('second')"]
    result = cli_runtime.run_cli_with_heartbeat(
        cmd, label="test", timeout=10, heartbeat_interval=1, on_chunk=on_chunk,
    )
    assert result.returncode == 0
    # Two stdout lines, in order.
    stdout_lines = [line for fd, line in captured if fd == "stdout"]
    assert stdout_lines == ["first", "second"]


def test_stderr_chunks_marked_with_stderr_fd():
    captured: list[tuple[str, str]] = []

    def on_chunk(line, fd):
        captured.append((fd, line.rstrip("\n")))

    cmd = [sys.executable, "-u", "-c",
           "import sys; sys.stderr.write('err-line\\n'); sys.stderr.flush()"]
    cli_runtime.run_cli_with_heartbeat(
        cmd, label="test", timeout=10, heartbeat_interval=1, on_chunk=on_chunk,
    )
    stderr_lines = [(fd, line) for fd, line in captured if fd == "stderr"]
    assert stderr_lines == [("stderr", "err-line")]


def test_timeout_kills_subprocess_and_raises():
    # Sleep longer than the timeout → expect TimeoutExpired.
    cmd = [sys.executable, "-u", "-c", "import time; time.sleep(30)"]
    with pytest.raises(subprocess.TimeoutExpired):
        cli_runtime.run_cli_with_heartbeat(
            cmd, label="test", timeout=1, heartbeat_interval=1,
        )


def test_on_chunk_exception_does_not_break_drain():
    """A buggy on_chunk handler should NOT abort the subprocess drain."""
    captured: list[str] = []
    call_count = {"n": 0}

    def on_chunk(line, fd):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated handler bug")
        captured.append(line.rstrip("\n"))

    cmd = [sys.executable, "-u", "-c",
           "print('a'); print('b'); print('c')"]
    result = cli_runtime.run_cli_with_heartbeat(
        cmd, label="test", timeout=10, heartbeat_interval=1, on_chunk=on_chunk,
    )
    assert result.returncode == 0
    # First call raised, but subsequent ones still landed.
    assert "b" in captured and "c" in captured


def test_no_on_chunk_still_collects_output():
    """Back-compat: on_chunk=None still works, output collected in stdout/stderr."""
    cmd = [sys.executable, "-u", "-c", "print('hello world')"]
    result = cli_runtime.run_cli_with_heartbeat(
        cmd, label="test", timeout=10, heartbeat_interval=1,
    )
    assert result.returncode == 0
    assert "hello world" in result.stdout


def test_heartbeat_fires_from_main_thread_during_active_drain():
    """Plan §4.4 + review I10: heartbeat must still fire from the main
    activity thread on a regular cadence while drain threads are
    reading stdout/stderr. Previously a 5 s sleep made the main loop
    silent for up to 5 s after the child exited; we replaced it with
    a 0.5 s event-driven wait, so a long-running child that emits
    bursts of lines should see *multiple* heartbeat calls. Counts the
    main-thread heartbeat() invocations against a child that lives
    for ~1.5 s emitting lines."""
    import threading
    heartbeat_count = {"n": 0}
    heartbeat_threads: set = set()

    def fake_heartbeat(*_a, **_k):
        heartbeat_count["n"] += 1
        heartbeat_threads.add(threading.current_thread().name)

    with patch.object(cli_runtime, "activity") as fake:
        fake.heartbeat = fake_heartbeat
        # ~1.5 s of activity: 3 prints at 500 ms apart.
        cmd = [
            sys.executable, "-u", "-c",
            "import sys, time;\n"
            "for i in range(3):\n"
            "    print(f'line-{i}', flush=True); time.sleep(0.5)",
        ]
        result = cli_runtime.run_cli_with_heartbeat(
            cmd, label="hb-test", timeout=10, heartbeat_interval=1,
        )
    assert result.returncode == 0
    # >=3 heartbeats expected: start + at least 2 during the 1.5 s run.
    # (was as low as 1 with the old 5 s sleep on short turns; B2.)
    assert heartbeat_count["n"] >= 3, (
        f"expected >=3 heartbeats from main thread, got {heartbeat_count['n']}"
    )
    # All heartbeats must fire from the same (main) thread — that's the
    # whole reason this helper exists (preserves Temporal's thread-local
    # activity context). The drain threads are named "*-drain".
    assert all("drain" not in t for t in heartbeat_threads), (
        f"heartbeat fired from drain thread(s): {heartbeat_threads}"
    )
