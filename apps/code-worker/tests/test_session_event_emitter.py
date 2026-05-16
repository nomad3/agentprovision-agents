"""Unit tests for `apps/code-worker/session_event_emitter.py`.

Covers:
  - Batching (chunks group into the next flush window)
  - Size cap (16 KB / 32 chunks)
  - Drop policy under back-pressure (reasoning/stdout/text dropped,
    lifecycle/tool_use never)
  - Fail-soft HTTP (non-2xx + exception both swallowed)
  - close() flushes remaining queued chunks
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from session_event_emitter import SessionEventEmitter


class _FakeResp:
    def __init__(self, status: int):
        self.status_code = status


class _FakeHttp:
    """Captures POST bodies; lets tests assert batch shapes."""

    def __init__(self, status: int = 200, raise_exc: Exception | None = None):
        self.calls: list[dict] = []
        self._status = status
        self._exc = raise_exc

    def post(self, url, json=None, headers=None):
        if self._exc is not None:
            raise self._exc
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp(self._status)

    def close(self):
        pass


def _make_emitter(http: _FakeHttp, *, flush_ms: int = 30) -> SessionEventEmitter:
    em = SessionEventEmitter(
        chat_session_id="s-test",
        tenant_id="t-test",
        platform="claude_code",
        attempt=1,
        api_base_url="http://api",
        api_internal_key="k",
        flush_ms=flush_ms,
    )
    em._http = http  # swap real httpx for fake — internal detail, but clean for tests
    return em


def test_emitter_disabled_when_no_chat_session_id():
    em = SessionEventEmitter(
        chat_session_id="",
        tenant_id="t",
        platform="claude_code",
    )
    assert not em.enabled
    em.emit_chunk("text", "hello")  # must not raise
    em.close()


def test_emitter_batches_chunks_within_flush_window():
    http = _FakeHttp()
    em = _make_emitter(http, flush_ms=30)
    try:
        for i in range(5):
            em.emit_chunk("text", f"line {i}\n")
        # Wait for at least one flush window
        time.sleep(0.2)
    finally:
        em.close()
    assert len(http.calls) >= 1
    # All five chunks should be in one batch (well under 32-chunk cap)
    total_chunks = sum(len(c["json"]["payload"]["batch"]) for c in http.calls)
    assert total_chunks == 5
    # Each chunk carries kind + chunk text
    first_batch = http.calls[0]["json"]["payload"]["batch"]
    for i, item in enumerate(first_batch):
        assert item["chunk_kind"] == "text"
        assert item["chunk"] == f"line {i}\n"
        assert item["attempt"] == 1


def test_emitter_size_cap_splits_batches():
    http = _FakeHttp()
    em = _make_emitter(http, flush_ms=200)  # long window so we control flushes
    try:
        # Enqueue 50 chunks — over the 32-chunk cap → must split.
        for i in range(50):
            em.emit_chunk("text", f"chunk-{i}\n")
        time.sleep(0.5)
    finally:
        em.close()
    # Total chunks must equal 50, split across batches.
    total = sum(len(c["json"]["payload"]["batch"]) for c in http.calls)
    assert total == 50
    # No single batch should exceed 32 chunks.
    for c in http.calls:
        assert len(c["json"]["payload"]["batch"]) <= 32


def test_drop_policy_drops_reasoning_under_backpressure():
    http = _FakeHttp()
    em = _make_emitter(http, flush_ms=10000)  # never flush during the test
    try:
        # Fill queue past the high-water mark so drop policy kicks in.
        for i in range(1100):
            em.emit_chunk("lifecycle", "lc\n")  # never dropped, fills queue
        em.emit_chunk("reasoning", "should-be-dropped\n")
        em.emit_chunk("tool_use", "must-not-be-dropped\n")
        # Snapshot counters before close (close drains everything)
        stats_before = em._stats()
    finally:
        em.close()
    # `reasoning` should be in the dropped-by-kind counter.
    assert stats_before["dropped"] >= 1
    assert stats_before.get("dropped_reasoning", 0) >= 1
    # lifecycle/tool_use never dropped
    assert stats_before.get("dropped_lifecycle", 0) == 0
    assert stats_before.get("dropped_tool_use", 0) == 0


def test_fail_soft_on_http_error():
    http = _FakeHttp(status=500)
    em = _make_emitter(http, flush_ms=20)
    try:
        em.emit_chunk("text", "hi\n")
        time.sleep(0.2)
    finally:
        stats = em.close()
    # Non-2xx counts as http_errors, but no exception escaped.
    assert stats["http_errors"] >= 1


def test_fail_soft_on_http_exception():
    http = _FakeHttp(raise_exc=ConnectionError("boom"))
    em = _make_emitter(http, flush_ms=20)
    try:
        em.emit_chunk("text", "hi\n")
        time.sleep(0.2)
    finally:
        stats = em.close()
    assert stats["http_errors"] >= 1


def test_close_flushes_remaining_chunks():
    http = _FakeHttp()
    # Long flush window — close() must still drain everything.
    em = _make_emitter(http, flush_ms=10000)
    em.emit_chunk("text", "tail-1\n")
    em.emit_chunk("text", "tail-2\n")
    em.close()
    # Must have at least one batch with the two tail chunks.
    total = sum(len(c["json"]["payload"]["batch"]) for c in http.calls)
    assert total == 2
