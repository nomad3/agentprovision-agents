"""Tests for the subprocess wrapper helpers in workflows.py.

Targets the previously-unexercised loop bodies:

  * ``_run``                 — line 177-190 (sync shell wrapper, raises on fail)
  * ``_run_long_command``    — line 193-244 (Popen + heartbeat loop)
  * ``_run_cli_with_heartbeat`` — line 247-317 (Popen + ThreadPool + heartbeat
    poll loop). Phase 4 stubbed this entire helper because heartbeats touch
    the Temporal activity context, which only exists inside the worker.

Strategy: patch ``workflows.activity.heartbeat`` to a counted-call no-op,
patch ``subprocess.Popen`` with a fake process whose ``communicate`` returns
fast, and assert on the heartbeat call counts and resulting CompletedProcess.
"""
from __future__ import annotations

import concurrent.futures
import subprocess

import pytest

import cli_runtime
import workflows as wf


# ── _run (177-190) ───────────────────────────────────────────────────────

class TestRunHelper:
    """The narrow shell-out wrapper that raises on non-zero exit."""

    def test_returns_stdout_stripped_on_success(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="hello\n", stderr="",
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        assert wf._run("echo hello") == "hello"

    def test_raises_runtime_error_on_non_zero(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=2, stdout="oops", stderr="bad thing",
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="Command failed"):
            wf._run("false")

    def test_passes_extra_env(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="ok", stderr="",
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        wf._run("noop", extra_env={"FOO": "bar"})
        assert captured["env"]["FOO"] == "bar"


# ── _run_long_command (193-244) ──────────────────────────────────────────

class _FakeLongPopen:
    """Fake Popen whose ``poll()`` returns None for ``polls_until_exit``
    iterations, then ``returncode`` thereafter. ``communicate()`` returns
    canned stdout/stderr."""

    def __init__(self, *, polls_until_exit=2, returncode=0, stdout="ok", stderr=""):
        self._polls_remaining = polls_until_exit
        self.returncode = None
        self._final_returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    def poll(self):
        if self._polls_remaining > 0:
            self._polls_remaining -= 1
            return None
        self.returncode = self._final_returncode
        return self._final_returncode

    def communicate(self, timeout=None):
        if self.returncode is None:
            self.returncode = self._final_returncode
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class TestRunLongCommand:
    """Drives the Popen + heartbeat loop in ``_run_long_command``."""

    @pytest.fixture(autouse=True)
    def _fast_loop(self, monkeypatch):
        """Make ``time.sleep`` instant and ``activity.heartbeat`` a counter."""
        monkeypatch.setattr(wf.time, "sleep", lambda *_a, **_kw: None)
        self.heartbeats: list[str] = []
        monkeypatch.setattr(
            wf.activity, "heartbeat", lambda msg=None: self.heartbeats.append(msg),
        )
        # Fake monotonic that grows by 1 per call so elapsed is deterministic.
        self._t = 0.0

        def fake_monotonic():
            self._t += 1.0
            return self._t

        monkeypatch.setattr(wf.time, "monotonic", fake_monotonic)
        yield

    def test_happy_path_returns_completed_process(self, monkeypatch):
        fake = _FakeLongPopen(polls_until_exit=2, returncode=0, stdout="done", stderr="")

        monkeypatch.setattr(
            wf.subprocess, "Popen", lambda *a, **kw: fake,
        )

        result = wf._run_long_command(
            ["echo", "hi"],
            cwd="/tmp",
            timeout=10_000,
            heartbeat_message="working",
            heartbeat_interval=1,
        )
        assert result.returncode == 0
        assert result.stdout == "done"
        # At least one heartbeat fired during the polling loop.
        assert any("working" in (h or "") for h in self.heartbeats)

    def test_non_zero_exit_raises(self, monkeypatch):
        fake = _FakeLongPopen(polls_until_exit=1, returncode=3, stdout="", stderr="boom")
        monkeypatch.setattr(wf.subprocess, "Popen", lambda *a, **kw: fake)

        with pytest.raises(RuntimeError, match="Command failed"):
            wf._run_long_command(
                ["bad"], cwd="/tmp", timeout=10_000,
                heartbeat_message="x", heartbeat_interval=1,
            )

    def test_timeout_kills_subprocess(self, monkeypatch):
        # Process never exits — poll always returns None.
        fake = _FakeLongPopen(polls_until_exit=10_000, returncode=0)
        monkeypatch.setattr(wf.subprocess, "Popen", lambda *a, **kw: fake)

        with pytest.raises(RuntimeError, match="timed out"):
            wf._run_long_command(
                ["sleeper"], cwd="/tmp", timeout=2,
                heartbeat_message="x", heartbeat_interval=1,
            )
        assert fake.killed is True


# ── _run_cli_with_heartbeat (247-317) ─────────────────────────────────────

class _FakeChatPopen:
    """Fake Popen for the heartbeat wrapper.

    ``communicate(timeout=...)`` blocks for ``block_seconds`` of real time
    before returning canned ``(stdout, stderr)``. We pair this with a small
    ``heartbeat_interval`` in the helper call so ``future.result(timeout=...)``
    in ``_run_cli_with_heartbeat`` times out N times (each timeout fires a
    heartbeat) before the future finally completes.

    For the timeout-expired test path, set ``raise_timeout_expired=True`` —
    the helper's _wait_and_drain catches ``TimeoutExpired`` and re-raises.
    """

    def __init__(
        self,
        *,
        block_seconds=0.05,
        returncode=0,
        stdout="result",
        stderr="",
        raise_timeout_expired=False,
    ):
        self._block_seconds = block_seconds
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._raise_timeout_expired = raise_timeout_expired
        self.killed = False

    def communicate(self, timeout=None):
        import time as _time

        if self._raise_timeout_expired:
            raise subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout)
        _time.sleep(self._block_seconds)
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True

    def poll(self):
        return None if not self.killed else self.returncode


class TestRunCliWithHeartbeat:
    """Phase 4 stubbed this helper out entirely. Phase 4.5 actually exercises
    the loop: heartbeat -> poll future -> heartbeat -> poll future -> done."""

    @pytest.fixture(autouse=True)
    def _patch_clocks(self, monkeypatch):
        self.heartbeats: list[str] = []
        monkeypatch.setattr(
            cli_runtime.activity, "heartbeat", lambda msg=None: self.heartbeats.append(msg),
        )
        self._t = 0.0

        def fake_monotonic():
            self._t += 1.0
            return self._t

        monkeypatch.setattr(cli_runtime.time, "monotonic", fake_monotonic)
        yield

    def test_loop_emits_heartbeats_until_subprocess_completes(self, monkeypatch):
        """Heartbeat must fire at start + on every future-result timeout iteration
        before the subprocess finally exits."""
        fake = _FakeChatPopen(block_seconds=0.05, returncode=0, stdout="OUT", stderr="")
        monkeypatch.setattr(cli_runtime.subprocess, "Popen", lambda *a, **kw: fake)

        # heartbeat_interval << block_seconds — each future.result(timeout=...)
        # times out quickly while ``communicate`` is still sleeping inside the
        # worker thread, forcing the loop to fire a "running..." heartbeat.
        result = cli_runtime.run_cli_with_heartbeat(
            ["fakecli"], label="Fake CLI",
            timeout=1000,
            env={}, cwd="/tmp",
            heartbeat_interval=0.005,
        )
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0
        assert result.stdout == "OUT"
        # Starting heartbeat + at least one in-flight heartbeat.
        assert any("starting" in (h or "") for h in self.heartbeats)
        assert any("running" in (h or "") for h in self.heartbeats)

    def test_subprocess_timeout_kills_and_reraises(self, monkeypatch):
        fake = _FakeChatPopen(raise_timeout_expired=True)
        monkeypatch.setattr(cli_runtime.subprocess, "Popen", lambda *a, **kw: fake)

        with pytest.raises(subprocess.TimeoutExpired):
            cli_runtime.run_cli_with_heartbeat(
                ["fakecli"], label="X",
                timeout=1, env={}, cwd="/tmp",
                heartbeat_interval=0.001,
            )
        # The inner _wait_and_drain calls kill() before re-raising.
        assert fake.killed is True

    def test_unhandled_exception_kills_subprocess(self, monkeypatch):
        """Any non-timeout exception in the future must still kill the
        subprocess — the BaseException handler at line 308 covers cancel."""

        class _ExplodingPopen:
            returncode = None
            killed = False

            def communicate(self, timeout=None):
                raise RuntimeError("boom")

            def kill(self):
                self.killed = True

            def poll(self):
                return None  # still alive when the killer runs

        fake = _ExplodingPopen()
        monkeypatch.setattr(cli_runtime.subprocess, "Popen", lambda *a, **kw: fake)

        with pytest.raises(RuntimeError, match="boom"):
            cli_runtime.run_cli_with_heartbeat(
                ["fakecli"], label="X",
                timeout=10, env={}, cwd="/tmp",
                heartbeat_interval=0.001,
            )
        assert fake.killed is True
