"""Passthrough parser used by Copilot and OpenCode executors (plan §2.4).

These CLIs don't yet have a richer stream-mapper. We forward every
line verbatim with `chunk_kind="stdout"` or `chunk_kind="stderr"` so
the terminal at least shows the raw JSONL stream the CLI emits — better
than the previous "nothing until completion" behaviour.
"""
from __future__ import annotations

from typing import Callable


def build_parser(emitter) -> Callable[[str, str], None]:
    def on_chunk(line: str, fd: str) -> None:
        if not line:
            return
        if fd == "stderr":
            emitter.emit_chunk("stderr", line, fd="stderr")
        else:
            emitter.emit_chunk("stdout", line, fd="stdout")
    return on_chunk
