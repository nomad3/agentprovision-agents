"""Claude `--output-format stream-json --verbose` parser.

Reads NDJSON events from Claude Code CLI and maps them to the
agentprovision `chunk_kind` taxonomy. See plan §2.1 for the
authoritative event→chunk table:

  system.init                   → lifecycle
  assistant.text                → text
  assistant.thinking            → reasoning (· prefix, dim)
  assistant.tool_use            → tool_use  (→ prefix)
  user.tool_result              → tool_result (← / ✗ prefix)
  result.success                → lifecycle  (✓ + cost + tok)
  result.error_*                → lifecycle_error (✗)

Edit-diff detection: when ``tool_use.name`` is one of
``{"Edit", "Write", "NotebookEdit"}``, emit a follow-up ``file: <path>``
line so the user sees what file is about to be touched.

The parser is a closure builder: ``build_parser(emitter)`` returns an
``on_chunk(line, fd)`` function suitable for plugging into
``cli_runtime.run_cli_with_heartbeat(..., on_chunk=...)``. The closure
owns a fragment buffer because the CLI's stdout chunk may contain
partial JSON (rare but possible — better safe than sorry).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


_EDIT_LIKE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})


def _abbrev(s: str, n: int = 200) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _format_tool_input(name: str, inp: Any) -> str:
    """One-line abbreviation of a tool_use input dict."""
    if isinstance(inp, dict):
        # Show file_path / pattern / command early — those are the
        # signal-carrying fields for the common tools.
        for key in ("file_path", "pattern", "command", "url", "path", "query"):
            if key in inp:
                return f"{key}={_abbrev(str(inp[key]), 120)}"
        # Fallback: short JSON.
        try:
            return _abbrev(json.dumps(inp, separators=(",", ":")), 200)
        except Exception:  # noqa: BLE001
            return _abbrev(str(inp), 200)
    if isinstance(inp, str):
        return _abbrev(inp, 200)
    return _abbrev(str(inp), 200)


def _format_tool_result(content: Any, is_error: bool) -> str:
    """Render a tool_result content — string or list-of-parts."""
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        # Claude tool_result content is sometimes [{"type":"text","text":"..."}]
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                else:
                    parts.append(json.dumps(part)[:120])
            else:
                parts.append(str(part))
        text = " ".join(parts)
    else:
        text = str(content) if content is not None else ""
    # If is_error, cap shorter and prefix.
    if is_error:
        return _abbrev(text, 300)
    return _abbrev(text, 400)


def parse_claude_event(
    obj: Dict[str, Any],
    tool_names: Optional[Dict[str, str]] = None,
) -> list[tuple[str, str]]:
    """Map a single parsed stream-json event to a list of (chunk_kind, chunk).

    Returns possibly-multiple tuples because some events fan out
    (e.g. tool_use → tool_use line + edit-target line for Edit tools).
    Returns ``[]`` for unrecognized events — caller decides whether to
    forward them as raw `stdout`.

    `tool_names` is a caller-owned dict mapping ``tool_use_id`` →
    ``name`` populated as ``assistant.tool_use`` events stream in and
    consulted on ``user.tool_result`` to render a human-friendly name
    instead of the opaque id (review I9). Pass None for tests that
    only want best-effort id rendering.
    """
    t = obj.get("type")
    out: list[tuple[str, str]] = []

    if t == "system":
        if obj.get("subtype") == "init":
            sid = obj.get("session_id") or ""
            sid_short = sid[:8] if sid else "?"
            tools = obj.get("tools") or []
            line = f"▷ init claude_code (session={sid_short}, tools={len(tools)})\n"
            out.append(("lifecycle", line))
        return out

    if t == "assistant":
        msg = obj.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            return out
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                txt = part.get("text") or ""
                if txt:
                    out.append(("text", txt if txt.endswith("\n") else txt + "\n"))
            elif ptype == "thinking":
                txt = part.get("thinking") or part.get("text") or ""
                if txt:
                    out.append(("reasoning", f"· thinking: {_abbrev(txt, 200)}\n"))
            elif ptype == "tool_use":
                name = part.get("name") or "?"
                inp = part.get("input")
                tool_id = part.get("id")
                # Stash id→name so the matching user.tool_result event
                # can render the human-readable tool name (review I9).
                if tool_names is not None and tool_id:
                    tool_names[tool_id] = name
                out.append(("tool_use", f"→ Tool({name}) {_format_tool_input(name, inp)}\n"))
                # Edit-diff detection: surface the target path on its
                # own line so the user can scan a session for "what
                # files changed" without expanding every tool_use.
                if name in _EDIT_LIKE_TOOLS and isinstance(inp, dict):
                    fp = inp.get("file_path") or inp.get("path")
                    if fp:
                        out.append(("tool_use", f"  file: {fp}\n"))
        return out

    if t == "user":
        # tool_result entries flow back as user.message.content[*].tool_result
        msg = obj.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            return out
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "tool_result":
                continue
            is_error = bool(part.get("is_error"))
            tool_use_id = part.get("tool_use_id")
            # Look up the friendly name from the assistant.tool_use we
            # saw earlier; fall back to the raw id, then to "tool"
            # (review I9 — never emit the bare uuid as "tool name").
            if tool_names is not None and tool_use_id and tool_use_id in tool_names:
                tool_name = tool_names[tool_use_id]
            else:
                tool_name = tool_use_id or "tool"
            rendered = _format_tool_result(part.get("content"), is_error)
            prefix = "✗" if is_error else "←"
            out.append(("tool_result", f"{prefix} {tool_name}: {rendered}\n"))
        return out

    if t == "result":
        sub = obj.get("subtype") or ""
        if sub == "success":
            cost = obj.get("total_cost_usd")
            usage = obj.get("usage") or {}
            in_tok = usage.get("input_tokens") or 0
            out_tok = usage.get("output_tokens") or 0
            cost_str = f"${float(cost):.4f}" if cost is not None else "$?"
            out.append((
                "lifecycle",
                f"✓ done · {cost_str} · {in_tok}/{out_tok} tok\n",
            ))
        elif sub.startswith("error") or sub.startswith("error_"):
            msg = obj.get("message") or obj.get("error") or sub
            out.append(("lifecycle_error", f"✗ {sub}: {_abbrev(str(msg), 200)}\n"))
        else:
            # Unknown result subtype — surface as lifecycle so it's
            # visible but doesn't poison the error path.
            out.append(("lifecycle", f"· result.{sub}\n"))
        return out

    # Unknown top-level event type — caller decides whether to fall
    # back to raw stdout passthrough.
    return out


def build_parser(emitter) -> Callable[[str, str], None]:
    """Build the `on_chunk` callback for cli_runtime.

    `emitter` is a SessionEventEmitter-like object exposing
    ``emit_chunk(chunk_kind, chunk, fd=..., raw=...)``.

    The closure:
      - Buffers partial lines (`stdout`) until a `\\n` arrives.
      - Parses each JSON line, maps to (chunk_kind, chunk) tuples.
      - On JSON parse failure, forwards the raw line as `stdout`.
      - Forwards `stderr` lines verbatim as `stderr` kind.
    """
    stdout_buf: list[str] = []
    # tool_use_id → tool name dict shared across the lifetime of this
    # parser (review I9). Populated on assistant.tool_use events,
    # consulted on user.tool_result. Bounded implicitly by turn length;
    # not pruned (a single Claude turn is finite).
    tool_names: Dict[str, str] = {}

    def _emit_parsed(raw_line: str) -> None:
        line = raw_line.rstrip("\n").rstrip("\r")
        if not line.strip():
            return
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # Not JSON — passthrough as raw stdout.
            emitter.emit_chunk("stdout", raw_line)
            return
        if not isinstance(obj, dict):
            emitter.emit_chunk("stdout", raw_line)
            return
        tuples = parse_claude_event(obj, tool_names=tool_names)
        if not tuples:
            # Recognized JSON but didn't map — drop quietly. Raw line
            # would just noise the terminal.
            return
        for kind, chunk in tuples:
            emitter.emit_chunk(kind, chunk, raw=obj if kind == "tool_use" else None)

    def on_chunk(line: str, fd: str) -> None:
        if fd == "stderr":
            # Pass stderr verbatim — claude's stderr is rare but useful
            # (warnings about deprecated flags, mcp errors).
            if line.strip():
                emitter.emit_chunk("stderr", line, fd="stderr")
            return
        # stdout: lines are normally complete because Popen bufsize=1
        # is line-buffered, but defensive concat just in case.
        if not line.endswith("\n"):
            stdout_buf.append(line)
            return
        if stdout_buf:
            stdout_buf.append(line)
            line = "".join(stdout_buf)
            stdout_buf.clear()
        _emit_parsed(line)

    return on_chunk
