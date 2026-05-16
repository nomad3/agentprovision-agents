"""Codex `codex exec --json` parser.

Maps codex stream events to `chunk_kind` per plan §2.2:

  reasoning.text              → reasoning  (· prefix)
  command                     → tool_use   ($ prefix)
  command.output              → stdout
  function_call / tool_call   → tool_use   (→ prefix)
  agent_message.text          → text
  last_message                → lifecycle  (✓ done)
  error                       → lifecycle_error (✗)

Unrecognized JSON lines fall through as `stdout` for raw debugging.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


def _abbrev(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def parse_codex_event(obj: Dict[str, Any]) -> list[tuple[str, str]]:
    """Map one parsed JSON event to (chunk_kind, chunk) tuples."""
    t = obj.get("type") or obj.get("kind") or ""
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    out: list[tuple[str, str]] = []

    if t in ("reasoning", "reasoning.text"):
        txt = (
            obj.get("text")
            or data.get("text")
            or obj.get("delta")
            or data.get("delta")
            or ""
        )
        if txt:
            out.append(("reasoning", f"· {_abbrev(txt, 240)}\n"))
        return out

    if t == "command":
        cmd = obj.get("command") or data.get("command") or obj.get("text") or ""
        if isinstance(cmd, list):
            cmd = " ".join(str(x) for x in cmd)
        if cmd:
            out.append(("tool_use", f"$ {_abbrev(str(cmd), 240)}\n"))
        return out

    if t in ("command.output", "command_output"):
        text = obj.get("output") or data.get("output") or obj.get("text") or ""
        if text:
            # Preserve newline if present, else add one.
            if not str(text).endswith("\n"):
                text = str(text) + "\n"
            out.append(("stdout", str(text)))
        return out

    if t in ("function_call", "tool_call"):
        name = obj.get("name") or data.get("name") or "?"
        args = obj.get("arguments") or data.get("arguments") or {}
        if isinstance(args, dict):
            try:
                args_str = json.dumps(args, separators=(",", ":"))
            except Exception:  # noqa: BLE001
                args_str = str(args)
        else:
            args_str = str(args)
        out.append(("tool_use", f"→ {name}({_abbrev(args_str, 180)})\n"))
        return out

    if t in ("agent_message", "agent_message.text"):
        txt = obj.get("text") or data.get("text") or ""
        if txt:
            out.append(("text", txt if str(txt).endswith("\n") else f"{txt}\n"))
        return out

    if t == "last_message":
        out.append(("lifecycle", "✓ done\n"))
        return out

    if t == "error":
        msg = obj.get("message") or data.get("message") or str(obj)
        out.append(("lifecycle_error", f"✗ {_abbrev(str(msg), 240)}\n"))
        return out

    return out


def build_parser(emitter) -> Callable[[str, str], None]:
    """Build the `on_chunk` callback for cli_runtime (codex variant)."""

    def on_chunk(line: str, fd: str) -> None:
        if fd == "stderr":
            if line.strip():
                emitter.emit_chunk("stderr", line, fd="stderr")
            return
        stripped = line.strip()
        if not stripped:
            return
        # codex --json emits one JSON object per line. If a line doesn't
        # parse, surface it as raw stdout so the user still sees the
        # output (codex sometimes mixes plain text and json depending
        # on what's installed in $PATH).
        if not stripped.startswith("{"):
            emitter.emit_chunk("stdout", line)
            return
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            emitter.emit_chunk("stdout", line)
            return
        if not isinstance(obj, dict):
            emitter.emit_chunk("stdout", line)
            return
        tuples = parse_codex_event(obj)
        if not tuples:
            # Unknown event type — fall through as stdout (best-effort
            # visibility for new codex event shapes).
            emitter.emit_chunk("stdout", line)
            return
        for kind, chunk in tuples:
            emitter.emit_chunk(kind, chunk, raw=obj if kind == "tool_use" else None)

    return on_chunk
