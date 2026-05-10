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


def run_cli_with_heartbeat(
    cmd: list[str],
    *,
    label: str,
    timeout: int = 1500,
    env: dict | None = None,
    cwd: str | None = None,
    heartbeat_interval: int = 30,
) -> subprocess.CompletedProcess:
    """Run a chat-CLI subprocess while heartbeating Temporal from the activity thread.

    Why: Temporal's sync-activity context lives in thread-local storage tied to
    the activity-execution thread. A bare ``threading.Thread`` does not inherit
    it, so ``activity.heartbeat()`` calls from a spawned heartbeat thread raise
    a "not in an activity context" error. With ``except Exception: pass``
    swallowing the failure, Temporal sees zero heartbeats and cancels the
    activity at ``heartbeat_timeout`` even when the subprocess is alive — which
    surfaces to callers as ``WorkflowFailureError: Workflow execution failed``.

    Fix: launch the subprocess via ``Popen``, drain it on a worker thread
    (``communicate`` reads stdout/stderr concurrently — no PIPE deadlock even
    on multi-MB CLI output), and heartbeat from the main activity thread while
    polling the future. On any exception path (Temporal cancellation,
    subprocess timeout) the subprocess is killed before re-raising, so a
    cancelled activity never leaves a live ``gemini``/``claude``/``codex``
    process behind.
    """
    import concurrent.futures

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
    )

    def _wait_and_drain() -> tuple[str, str]:
        try:
            return proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate()
            except Exception:
                pass
            raise

    activity.heartbeat(f"{label} starting...")
    start = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_wait_and_drain)
            while True:
                try:
                    stdout, stderr = future.result(timeout=heartbeat_interval)
                    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
                except concurrent.futures.TimeoutError:
                    elapsed = int(time.monotonic() - start)
                    activity.heartbeat(f"{label} running... ({elapsed}s elapsed)")
    except BaseException:
        # Cancellation, subprocess timeout, or any other exit — don't let the
        # CLI subprocess outlive this activity. Kill it before the
        # ThreadPoolExecutor's __exit__ blocks on shutdown(wait=True).
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        raise
