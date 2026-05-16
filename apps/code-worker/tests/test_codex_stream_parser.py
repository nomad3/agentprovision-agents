"""Unit tests for `apps/code-worker/cli_executors/codex_stream_parser.py`.

Covers the codex `--json` event taxonomy: reasoning, command,
command.output, function_call, agent_message, last_message, error.
"""
from __future__ import annotations

import json

from cli_executors.codex_stream_parser import build_parser, parse_codex_event


class _StubEmitter:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def emit_chunk(self, chunk_kind, chunk, *, fd="stdout", raw=None):
        self.calls.append((chunk_kind, chunk))


def _feed(parser, lines):
    for ln in lines:
        if not ln.endswith("\n"):
            ln = ln + "\n"
        parser(ln, "stdout")


def test_reasoning_event_emits_reasoning_chunk():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "reasoning", "text": "considering the design..."})])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "reasoning"
    assert chunk.startswith("· ")
    assert "considering" in chunk


def test_command_event_emits_tool_use_with_dollar_prefix():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "command", "command": ["ls", "-la"]})])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "tool_use"
    assert chunk.startswith("$ ")
    assert "ls -la" in chunk


def test_command_output_emits_stdout():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "command.output", "output": "file1.py\nfile2.py"})])
    assert len(em.calls) == 1
    assert em.calls[0][0] == "stdout"


def test_function_call_emits_tool_use():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "function_call",
        "name": "read_file",
        "arguments": {"path": "main.py"},
    })])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "tool_use"
    assert "→ read_file" in chunk


def test_agent_message_emits_text():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "agent_message", "text": "Here is the answer."})])
    assert em.calls == [("text", "Here is the answer.\n")]


def test_last_message_emits_lifecycle_done():
    out = parse_codex_event({"type": "last_message"})
    assert out == [("lifecycle", "✓ done\n")]


def test_error_emits_lifecycle_error():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "error", "message": "auth failed"})])
    assert em.calls[0][0] == "lifecycle_error"
    assert "auth failed" in em.calls[0][1]


def test_unrecognized_json_falls_through_as_stdout():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({"type": "something.new", "data": {"x": 1}})])
    assert len(em.calls) == 1
    assert em.calls[0][0] == "stdout"


def test_plain_text_line_falls_through_as_stdout():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, ["plain text output line"])
    assert em.calls[0][0] == "stdout"
