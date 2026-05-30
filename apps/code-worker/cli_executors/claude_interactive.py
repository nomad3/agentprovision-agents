"""PTY-backed Claude Code interactive runner.

Claude Code's machine-readable JSON output is tied to ``claude -p``.
When a tenant needs to use a native Claude Code subscription session
instead of the print/API path, the worker has to drive the normal TTY UI
and treat the terminal transcript as the result.

This module is intentionally small and stdlib-only: production images do
not currently include tmux/expect, and adding another daemon just to keep
Claude attached would be heavier than a per-turn PTY bridge.
"""
from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import time
from collections.abc import Callable


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")
# Approach C transcript chrome: the bracketed-paste placeholder the REPL emits
# when input collapses, and the Read tool-call chrome around the turn-file read.
_PASTED_RE = re.compile(r"^\[Pasted text\b.*\]$")
_READ_CALL_RE = re.compile(r"^[⏺·•*-]?\s*Read\(.*\)\s*$")
_READ_RESULT_RE = re.compile(r"^[⎿|]?\s*Read(?:\s+\d|ing\b).*$")
# Folder-trust dialog markers — if one appears before we submit we send a bare
# Enter to accept (belt-and-suspenders; #732 normally pre-seeds trust).
_TRUST_RE = re.compile(r"\b(do you trust|trust this folder|trust the files)\b", re.I)


def clean_interactive_transcript(raw: str, prompt: str = "") -> str:
    """Return a readable answer from a Claude Code terminal transcript.

    This is a best-effort fallback, not a protocol parser. The interactive
    UI is meant for humans, so we strip ANSI/control noise and common box/
    prompt chrome while preserving useful assistant text and command output.

    Approach C (plan 2026-05-30) submits a single-line trigger that makes
    Claude ``Read`` a turn-file, so we also drop (a) the trigger echo, (b) any
    ``[Pasted text +N lines]`` placeholder, and (c) the ``Read`` tool chrome,
    leaving just Claude's reply. Never raises.
    """
    try:
        text = _OSC_RE.sub("", raw)
        text = _ANSI_RE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        prompt = (prompt or "").strip()

        cleaned: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if cleaned and cleaned[-1]:
                    cleaned.append("")
                continue
            if prompt and stripped in {prompt, f"> {prompt}"}:
                continue
            if stripped in {"/exit", "exit"}:
                continue
            if stripped.startswith(("╭", "╰", "│", "┌", "└", "┃", "┗", "┏")):
                continue
            if stripped in {"?", ">", "Welcome to Claude Code"}:
                continue
            if stripped.startswith(("Claude Code", "By using Claude Code")):
                continue
            # Approach C chrome.
            if _PASTED_RE.match(stripped):
                continue
            if _READ_CALL_RE.match(stripped) or _READ_RESULT_RE.match(stripped):
                continue
            cleaned.append(stripped)

        return "\n".join(cleaned).strip()
    except Exception:  # noqa: BLE001 - best-effort cleaner must never raise
        return (raw or "").strip()


def decide_pty_action(
    *,
    now: float,
    start: float,
    last_output: float,
    seen_output: bool,
    submitted: bool,
    response_seen: bool,
    exit_sent_at: float | None,
    first_output_seconds: float,
    submit_settle_seconds: float,
    idle_exit_seconds: float,
    exit_grace_seconds: float,
    submitted_at: float | None = None,
) -> str:
    """Decide the next PTY action for one loop tick (pure — no I/O).

    Returns one of: ``"wait"`` (keep reading), ``"submit"`` (type the trigger
    once), ``"exit"`` (send ``/exit``), ``"terminate"`` (escalate to SIGTERM
    after the exit grace), or ``"kill"`` (SIGKILL — nothing rendered in time).

    State machine (post-#735, Approach C):
      1. Readiness — wait for the banner; if none within ``first_output_seconds``
         → kill. Once seen, require ``submit_settle_seconds`` of quiet (input box
         rendered + stable) before typing.
      2. Submit (once) — when settled and not yet submitted → submit.
      3. Await response — after submit, suppress the idle ``/exit`` until the
         FIRST post-submit output; if none within ``first_output_seconds`` after
         submit → kill.
      4. Idle exit — once the response is seen, ``/exit`` after
         ``idle_exit_seconds`` quiet, then SIGTERM after ``exit_grace_seconds``.
    """
    # 4b. Exit already sent — escalate after the grace window.
    if exit_sent_at is not None:
        if now - exit_sent_at >= exit_grace_seconds:
            return "terminate"
        return "wait"

    # 1. Pre-banner readiness gate.
    if not seen_output:
        if now - start >= first_output_seconds:
            return "kill"
        return "wait"

    # 2. Not yet submitted: type the trigger once the input box has settled.
    if not submitted:
        if now - last_output >= submit_settle_seconds:
            return "submit"
        return "wait"

    # 3. Submitted but no response yet: suppress idle /exit, bound the wait.
    if not response_seen:
        baseline = submitted_at if submitted_at is not None else start
        if now - baseline >= first_output_seconds:
            return "kill"
        return "wait"

    # 4a. Response seen: /exit after the idle window of quiet.
    if now - last_output >= idle_exit_seconds:
        return "exit"
    return "wait"


def _signal_tree(pgid: int, sig: int) -> None:
    """Signal Claude's whole process group (cached PGID) so children it spawned
    (MCP servers, helper procs) are reaped too — not just the top-level PID.

    Takes the PGID captured while the leader was alive, NOT a live
    ``os.getpgid(pid)`` lookup: if Claude exits before one of its children, that
    lookup raises ``ProcessLookupError`` even though the group is still alive,
    and we'd leak the orphaned children this is meant to reap."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def run_claude_interactive_with_heartbeat(
    cmd: list[str],
    *,
    prompt: str,
    label: str,
    timeout: int,
    env: dict[str, str],
    cwd: str,
    on_chunk: Callable[[str, str], None] | None = None,
    heartbeat: Callable[[str], None] | None = None,
    idle_exit_seconds: float | None = None,
    exit_grace_seconds: float | None = None,
    first_output_seconds: float | None = None,
    submit_settle_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Claude Code attached to a PTY and return a CompletedProcess.

    The interactive REPL (Claude Code v2.1.144) does NOT auto-execute a
    positional ``[prompt]`` arg, so the caller no longer appends one. Instead
    ``prompt`` is a single-line trigger we TYPE into the REPL once it's ready
    (Approach C, plan 2026-05-30): after the banner appears we wait a short
    ``submit_settle_seconds`` quiet window (input box rendered + stable), then
    write the trigger + ``\r``. Submission is gated so we never type into a
    not-yet-ready REPL.

    Since the interactive CLI does not exit after a turn, we send ``/exit`` once
    the terminal has been quiet for ``idle_exit_seconds`` — but only *after* a
    post-submit response is seen. Before the banner the idle countdown is
    suppressed and we wait up to ``first_output_seconds``; after submit we again
    suppress it until the first post-submit output (bounded by the same cap).
    Without these gates a slow launch / pre-response quiet was ``/exit``'d and
    the turn died with an empty transcript. Process-group cleanup (#735) is
    unchanged.
    """
    idle_exit_seconds = idle_exit_seconds if idle_exit_seconds is not None else float(
        os.environ.get("CLAUDE_CODE_INTERACTIVE_IDLE_EXIT_SECONDS", "8")
    )
    exit_grace_seconds = exit_grace_seconds if exit_grace_seconds is not None else float(
        os.environ.get("CLAUDE_CODE_INTERACTIVE_EXIT_GRACE_SECONDS", "10")
    )
    first_output_seconds = first_output_seconds if first_output_seconds is not None else float(
        os.environ.get("CLAUDE_CODE_INTERACTIVE_FIRST_OUTPUT_SECONDS", "90")
    )
    submit_settle_seconds = submit_settle_seconds if submit_settle_seconds is not None else float(
        os.environ.get("CLAUDE_CODE_INTERACTIVE_SUBMIT_SETTLE_SECONDS", "1.0")
    )
    submit_bytes = ((prompt or "").encode() + b"\r") if prompt else b""

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
        # Own session/process group so we can signal Claude AND any children it
        # spawned (MCP servers, helper procs) as a unit — a bare proc.kill()
        # would orphan them and leak resources on repeated timeouts.
        start_new_session=True,
    )
    os.close(slave_fd)
    # Capture the PGID now, while the leader is alive, and reuse it for every
    # cleanup signal — a later os.getpgid() off a dead leader would miss a
    # still-running child group. start_new_session makes pgid == proc.pid.
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid

    chunks: list[str] = []
    start = time.monotonic()
    last_output = start
    last_heartbeat = start
    exit_sent_at: float | None = None
    seen_output = False
    # Approach C submission state.
    submitted = False
    submitted_at: float | None = None
    response_seen = False
    trust_acked = False

    try:
        while True:
            now = time.monotonic()
            if heartbeat and now - last_heartbeat >= 30:
                heartbeat(f"{label} interactive ({int(now - start)}s elapsed)")
                last_heartbeat = now
            if now - start >= timeout:
                _signal_tree(pgid, signal.SIGKILL)
                break

            ready, _, _ = select.select([master_fd], [], [], 0.25)
            if ready:
                try:
                    data = os.read(master_fd, 8192)
                except OSError:
                    data = b""
                if data:
                    text = data.decode(errors="replace")
                    chunks.append(text)
                    last_output = now
                    seen_output = True
                    # First output AFTER submit = Claude is responding; this
                    # un-suppresses the idle `/exit`.
                    if submitted and not response_seen:
                        response_seen = True
                    if on_chunk:
                        on_chunk(text, "stdout")
                    # Belt-and-suspenders: a folder-trust dialog may precede the
                    # input box despite #732's seed. Accept it once with a bare
                    # Enter so the input box renders before we type the trigger.
                    if not submitted and not trust_acked and _TRUST_RE.search(text):
                        try:
                            os.write(master_fd, b"\r")
                        except OSError:
                            pass
                        trust_acked = True
                    continue

            if proc.poll() is not None:
                break

            action = decide_pty_action(
                now=now,
                start=start,
                last_output=last_output,
                seen_output=seen_output,
                submitted=submitted,
                response_seen=response_seen,
                exit_sent_at=exit_sent_at,
                submitted_at=submitted_at,
                first_output_seconds=first_output_seconds,
                submit_settle_seconds=submit_settle_seconds,
                idle_exit_seconds=idle_exit_seconds,
                exit_grace_seconds=exit_grace_seconds,
            )

            if action == "wait":
                continue
            if action == "submit":
                if submit_bytes:
                    os.write(master_fd, submit_bytes)
                submitted = True
                submitted_at = now
                # Reset the idle baseline so the post-submit response gate (not a
                # stale pre-submit quiet) governs the next decision.
                last_output = now
                continue
            if action == "exit":
                os.write(master_fd, b"\n/exit\n")
                exit_sent_at = now
                continue
            if action == "terminate":
                _signal_tree(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    _signal_tree(pgid, signal.SIGKILL)
                break
            if action == "kill":
                _signal_tree(pgid, signal.SIGKILL)
                break
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    try:
        returncode = proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _signal_tree(pgid, signal.SIGKILL)
        returncode = proc.wait(timeout=1)

    raw = "".join(chunks)
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout=clean_interactive_transcript(raw, prompt),
        stderr="" if returncode == 0 else raw,
    )


__all__ = [
    "clean_interactive_transcript",
    "decide_pty_action",
    "run_claude_interactive_with_heartbeat",
]
