"""Shared CLI runtime helpers for code-worker chat executors.

Phase 1.6 hoist: this module owns the two helpers that every per-platform
chat executor reaches for — the heartbeat-aware subprocess wrapper and
the streaming-JSON-safe error-snippet builder. Bodies are byte-identical
to their previous home in workflows.py (just with the leading underscore
dropped and the public re-export kept on the workflows side for
production callers and the existing test patches).

Why: we are about to split the 2,318-line workflows.py into per-CLI
executor modules (cli_executors/*.py). Those modules need a stable,
top-level helper to call without re-importing workflows (which would
create a cycle: workflows -> cli_executors -> workflows). Giving them
``cli_runtime`` as a direct dependency breaks that cycle cleanly.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time

from temporalio import activity

logger = logging.getLogger(__name__)


def safe_cli_error_snippet(stderr: str, stdout: str, max_len: int = 800) -> str:
    """Build a useful error snippet from a CLI subprocess that exited non-zero.

    Why this exists: several CLIs (GitHub Copilot CLI, OpenCode, Codex,
    Gemini) emit *streaming JSON* on stdout. When the CLI exits 1 with
    no stderr but a stdout full of `{"type": "session.skills_loaded", ...}`
    style events, the old `result.stderr or result.stdout` pattern picks
    up the streaming JSON, packs it into the error message, and that
    error text eventually surfaces to the user as the chat reply
    (`CLI exit 1: {"type":"session.skills_loaded",...}`). 2026-05-05
    incident: every chat turn whose primary CLI hit any failure showed
    raw JSON to the user instead of a graceful fallback.

    Strategy:
      1. Prefer stderr — it's almost never streaming JSON.
      2. If stderr is empty, scan stdout for an `error`-shaped event
         (most CLIs emit `{"type":"error","message":"..."}` on failure)
         and return its message.
      3. Otherwise return a generic "no error detail available" so the
         routing layer's classifier can still bucket the failure into
         exception/quota/auth without echoing the JSON to the user.
    """
    err = (stderr or "").strip()
    if err:
        return err[:max_len]
    out = (stdout or "").strip()
    if not out:
        return ""
    # Detect streaming-JSON output (Copilot / OpenCode / Codex / Gemini all
    # share this shape) — first non-empty line starts with `{` and parses
    # as JSON with a `type` field.
    first_nonblank = next((ln for ln in out.splitlines() if ln.strip()), "")
    if first_nonblank.startswith("{") and '"type"' in first_nonblank:
        # Parse line-by-line looking for an error event.
        for line in out.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            etype = obj.get("type", "")
            # Common shapes across the CLIs we ship.
            if etype in ("error", "exception", "session.error", "result.error"):
                msg = obj.get("message") or obj.get("data", {}).get("message") or str(obj)
                return msg[:max_len]
            if etype == "result" and obj.get("error"):
                return str(obj["error"])[:max_len]
        # Found streaming JSON but no error event — return a generic
        # "see logs" message so we don't leak the stream into chat.
        return f"<{len(out)} bytes of streaming JSON, no error event>"
    # Plain text — safe to return as-is.
    return out[:max_len]


def emit_heartbeat_missed_event(
    *,
    tenant_id: str,
    run_id: str,
    last_seen_ts: float,
    parent_workflow_id: str | None = None,
    parent_task_id: str | None = None,
    api_base_url: str | None = None,
    api_internal_key: str | None = None,
) -> bool:
    """POST execution.heartbeat_missed to the api internal endpoint.

    Phase 3 commit 8 worker-side emit. Fire-and-forget — never raises;
    returns True on 2xx, False otherwise. Caller decides whether to
    backoff or not.

    Used by the heartbeat-poll loop when staleness exceeds
    ``2 * heartbeat_interval`` (per design §9.1).
    """
    import os as _os
    base = api_base_url or _os.environ.get("API_BASE_URL", "http://api")
    key = api_internal_key or _os.environ.get("API_INTERNAL_KEY", "")
    url = f"{base.rstrip('/')}/api/v1/internal/orchestrator/events"
    body = {
        "event_type": "execution.heartbeat_missed",
        "tenant_id": tenant_id,
        "payload": {
            "run_id": run_id,
            "last_seen_ts": last_seen_ts,
            "parent_workflow_id": parent_workflow_id,
            "parent_task_id": parent_task_id,
        },
    }
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            resp = client.post(
                url, json=body,
                headers={"X-Internal-Key": key},
            )
            return 200 <= resp.status_code < 300
    except Exception:  # noqa: BLE001
        return False


def run_cli_with_heartbeat(
    cmd: list[str],
    *,
    label: str,
    timeout: int = 1500,
    env: dict | None = None,
    cwd: str | None = None,
    heartbeat_interval: int = 30,
    on_chunk=None,  # Callable[[str, str], None] | None — (line, fd_name)
) -> subprocess.CompletedProcess:
    """Run a chat-CLI subprocess while heartbeating Temporal from the activity thread.

    Why: Temporal's sync-activity context lives in thread-local storage tied to
    the activity-execution thread. A bare ``threading.Thread`` does not inherit
    it, so ``activity.heartbeat()`` calls from a spawned heartbeat thread raise
    a "not in an activity context" error. With ``except Exception: pass``
    swallowing the failure, Temporal sees zero heartbeats and cancels the
    activity at ``heartbeat_timeout`` even when the subprocess is alive — which
    surfaces to callers as ``WorkflowFailureError: Workflow execution failed``.

    Streaming pump (2026-05-16 §4.4):
        Previous impl used ``proc.communicate(timeout=...)`` which buffers
        the *entire* stdout/stderr to completion. Switched to dual
        line-reader threads (``_drain``) so each line fires ``on_chunk``
        as it arrives — that's what lets the terminal card show real-time
        Claude reasoning + tool calls instead of an empty progress bar
        for 20s.

    On any exception path (Temporal cancellation, subprocess timeout) the
    subprocess is killed before re-raising, so a cancelled activity never
    leaves a live ``gemini``/``claude``/``codex`` process behind.
    """
    import threading as _threading

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered — pairs with the line-reader threads
        env=env,
        cwd=cwd,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    # Event the drain threads set after EOF (stream closed). The main
    # loop waits on this with a short timeout instead of blocking on a
    # 5-second sleep — that drops tail-latency on short Claude turns
    # from ~5 s to <0.5 s (review B2). The Event is set TWICE in the
    # happy path (once per drain thread) and that's fine — Event.set()
    # is idempotent.
    drains_done = _threading.Event()
    drains_remaining = [2]  # mutable counter shared by both drain threads
    drains_lock = _threading.Lock()

    def _drain(stream, sink: list[str], fd_name: str) -> None:
        # ``iter(stream.readline, "")`` is the canonical "read until
        # EOF" idiom — terminates when the child closes the FD.
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
                if on_chunk is not None:
                    try:
                        on_chunk(line, fd_name)
                    except Exception:  # noqa: BLE001
                        # on_chunk must never break the drain. Stream
                        # emitter has its own fail-soft logic; anything
                        # else is the caller's bug, log and continue.
                        logger.debug(
                            "on_chunk handler raised (fd=%s); continuing drain",
                            fd_name, exc_info=True,
                        )
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            # Signal main loop once both drains have closed their streams.
            with drains_lock:
                drains_remaining[0] -= 1
                if drains_remaining[0] <= 0:
                    drains_done.set()

    t_out = _threading.Thread(
        target=_drain, args=(proc.stdout, stdout_lines, "stdout"),
        name=f"{label}-stdout-drain", daemon=True,
    )
    t_err = _threading.Thread(
        target=_drain, args=(proc.stderr, stderr_lines, "stderr"),
        name=f"{label}-stderr-drain", daemon=True,
    )
    t_out.start()
    t_err.start()

    activity.heartbeat(f"{label} starting...")
    start = time.monotonic()
    try:
        # Heartbeat-while-alive on the main activity thread (preserves
        # Temporal's thread-local activity context — see top docstring).
        while True:
            rc = proc.poll()
            if rc is not None:
                # Child exited — wait for the drain threads so we don't
                # lose trailing lines that arrived after the last sleep.
                t_out.join(timeout=5)
                t_err.join(timeout=5)
                return subprocess.CompletedProcess(
                    cmd, rc, "".join(stdout_lines), "".join(stderr_lines),
                )
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                # Match subprocess.TimeoutExpired semantics — kill, wait,
                # raise so callers' try/except paths still work.
                proc.kill()
                t_out.join(timeout=2)
                t_err.join(timeout=2)
                raise subprocess.TimeoutExpired(cmd, timeout)
            activity.heartbeat(f"{label} running... ({int(elapsed)}s elapsed)")
            # Wake on EITHER a drain-side signal (stream closed → child
            # likely just exited) OR a short timeout cap. The cap is
            # min(heartbeat_interval, 0.5) so heartbeat cadence still
            # tightens to ≤ heartbeat_interval s when the caller passes
            # a sub-second value. This gives a tail latency of <500 ms
            # while keeping poll() rate ≤ 2/s (review B2).
            wake_timeout = min(heartbeat_interval, 0.5)
            if drains_done.wait(timeout=wake_timeout):
                # Drain signalled — drain_done can ONLY be set after
                # both pipes hit EOF, which in turn only happens after
                # the child either exits cleanly or is killed. Loop
                # around to poll() once more to pick up the exit code;
                # don't break here in case the child is still flushing
                # its exit status to the OS.
                continue
    except BaseException:
        # Cancellation, subprocess timeout, or any other exit — don't let the
        # CLI subprocess outlive this activity. The poll() call below may
        # itself raise (rare, but undefined per CPython source when the
        # subprocess is in a weird state), so we wrap it defensively —
        # an unconditional kill() is the safest fallback (review B1).
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        # Give drain threads a moment to flush so any captured trailing
        # output isn't lost when we re-raise.
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        raise
