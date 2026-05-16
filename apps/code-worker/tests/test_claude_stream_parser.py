"""Unit tests for `apps/code-worker/cli_executors/claude_stream_parser.py`.

Feed canned NDJSON events through `build_parser(emitter)` and assert
(`chunk_kind`, `chunk`) tuples landed on the emitter in order. Covers:

  - system.init        → lifecycle (▷ init claude_code ...)
  - assistant.text     → text
  - tool_use[Edit]     → tool_use + follow-up `file:` line
  - tool_result(error) → tool_result (✗ prefix)
  - result.success     → lifecycle (✓ done · $... · in/out tok)
"""
from __future__ import annotations

import json

from cli_executors.claude_stream_parser import build_parser, parse_claude_event


class _StubEmitter:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        # Mimic the SessionEventEmitter signature: emit_chunk(kind, chunk, fd=..., raw=...)

    def emit_chunk(self, chunk_kind, chunk, *, fd="stdout", raw=None):
        self.calls.append((chunk_kind, chunk))


def _feed(parser, lines):
    """Feed one or more raw stdout lines through the parser closure."""
    for ln in lines:
        if not ln.endswith("\n"):
            ln = ln + "\n"
        parser(ln, "stdout")


def test_system_init_emits_lifecycle():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "system",
        "subtype": "init",
        "session_id": "abcdef1234567890",
        "tools": ["Read", "Edit", "Bash"],
    })])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "lifecycle"
    assert "▷ init claude_code" in chunk
    assert "session=abcdef12" in chunk
    assert "tools=3" in chunk


def test_assistant_text_emits_text_chunk():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Hello, world!"}]},
    })])
    assert em.calls == [("text", "Hello, world!\n")]


def test_assistant_thinking_emits_reasoning():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "Let me consider this..."}]},
    })])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "reasoning"
    assert "· thinking:" in chunk


def test_tool_use_edit_emits_tool_use_plus_file_line():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Edit",
            "input": {"file_path": "apps/api/app/main.py", "old_string": "x", "new_string": "y"},
        }]},
    })])
    assert len(em.calls) == 2
    assert em.calls[0][0] == "tool_use"
    assert "→ Tool(Edit)" in em.calls[0][1]
    assert em.calls[1][0] == "tool_use"
    assert "  file: apps/api/app/main.py" in em.calls[1][1]


def test_tool_result_error_emits_tool_result_with_cross_prefix():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "is_error": True,
            "content": "File not found: /etc/secret",
        }]},
    })])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "tool_result"
    assert chunk.startswith("✗")
    assert "File not found" in chunk


def test_tool_result_success_emits_left_arrow_prefix():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "is_error": False,
            "content": "ok",
        }]},
    })])
    # No prior assistant.tool_use → no id→name map entry → falls back to
    # "tool" (review I9). The "ok" content still shows verbatim.
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "tool_result"
    assert chunk.startswith("←")
    assert "ok" in chunk


def test_tool_result_renders_friendly_tool_name_from_prior_tool_use():
    """Plan §2.1 / review I9: when a user.tool_result event arrives,
    the rendered line MUST include the human-readable tool name
    (e.g. "Read") taken from the matching assistant.tool_use event,
    not the opaque tool_use_id uuid."""
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [
        # First the assistant declares the tool_use with id+name.
        json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "id": "toolu_01ABC",
                "name": "Read",
                "input": {"file_path": "/etc/hosts"},
            }]},
        }),
        # Then the matching tool_result arrives by id.
        json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_01ABC",
                "is_error": False,
                "content": "127.0.0.1 localhost",
            }]},
        }),
    ])
    # Expect: tool_use line first, then tool_result with friendly name.
    kinds = [k for k, _ in em.calls]
    assert "tool_use" in kinds
    tr_chunk = next(c for k, c in em.calls if k == "tool_result")
    assert "Read" in tr_chunk, f"expected friendly tool name 'Read' in {tr_chunk!r}"
    assert "127.0.0.1 localhost" in tr_chunk
    # And critically: the raw id MUST NOT appear in the rendered text
    # (otherwise we've leaked the uuid that we tried to swap out).
    assert "toolu_01ABC" not in tr_chunk


def test_result_success_emits_lifecycle_with_cost_and_tokens():
    em = _StubEmitter()
    parser = build_parser(em)
    _feed(parser, [json.dumps({
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.0234,
        "usage": {"input_tokens": 2104, "output_tokens": 890},
    })])
    assert len(em.calls) == 1
    kind, chunk = em.calls[0]
    assert kind == "lifecycle"
    assert "✓ done" in chunk
    assert "$0.0234" in chunk
    assert "2104/890 tok" in chunk


def test_result_error_emits_lifecycle_error():
    obj = {"type": "result", "subtype": "error_quota", "message": "Rate limit exceeded"}
    out = parse_claude_event(obj)
    assert len(out) == 1
    kind, chunk = out[0]
    assert kind == "lifecycle_error"
    assert "✗ error_quota" in chunk


def test_non_json_line_passthrough_as_stdout():
    em = _StubEmitter()
    parser = build_parser(em)
    parser("not json at all\n", "stdout")
    # Falls through as raw stdout chunk
    assert em.calls == [("stdout", "not json at all\n")]


def test_stderr_line_emitted_as_stderr():
    em = _StubEmitter()
    parser = build_parser(em)
    parser("something happened\n", "stderr")
    assert len(em.calls) == 1
    assert em.calls[0][0] == "stderr"
