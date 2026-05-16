"""SessionEventEmitter — worker-side helper that batches CLI stream
chunks and fans them out to the API's internal stream endpoint.

Design: docs/plans/2026-05-16-terminal-full-cli-output.md §4.3, §6.1

Why batch?
----------
A Claude `--output-format stream-json` run emits 50-200 events/sec on
tool-heavy turns. One HTTP call per event would hammer the API + the
per-session advisory lock + Postgres. We batch with three caps:

  * 150 ms flush window (configurable via WORKER_STREAM_FLUSH_MS)
  * 32 chunks per batch
  * 16 KB total payload size per batch

Fail-soft
---------
HTTP errors NEVER raise. Subprocess output must not block on the
emit channel — if the API is unreachable, we drop the batch with a
WARNING log and a counter bump. Subscribers can reconnect and replay
once the API is back; missing inflight chunks degrade gracefully into
a coalesced gap in the terminal.

Drop policy
-----------
At queue depth >1000 we drop chunks in this priority order:

  1. ``reasoning``      (cosmetic — model's interior monologue)
  2. ``stdout``         (verbose raw passthrough)
  3. ``text``           (assistant prose — least important once 1000+ deep)

We NEVER drop ``lifecycle``, ``lifecycle_error``, ``tool_use``, or
``tool_result`` chunks — those carry the structural skeleton of the
session and the user needs them for context.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# Flush cadence: 150ms strikes a good balance between latency (user
# sees output ~6Hz, smooth) and API load (~7 publishes/sec/session,
# fine for the advisory lock budget per design §6.2).
_DEFAULT_FLUSH_MS = int(os.environ.get("WORKER_STREAM_FLUSH_MS", "150"))
_MAX_BATCH_CHUNKS = 32
_MAX_BATCH_BYTES = 16 * 1024  # 16 KB
_QUEUE_HIGH_WATER = 1000  # drop policy kicks in above this depth

# Chunk kinds that are NEVER dropped under back-pressure (carry
# session structure / errors). Order in ``_DROP_PRIORITY`` is the
# eviction order from cheapest to most painful.
_NEVER_DROP_KINDS = frozenset({
    "lifecycle", "lifecycle_error", "tool_use", "tool_result",
})
_DROP_PRIORITY = ("reasoning", "stdout", "text")


class SessionEventEmitter:
    """Background-flushed batcher for `cli_subprocess_stream` events.

    Usage::

        emitter = SessionEventEmitter(
            chat_session_id=task_input.chat_session_id,
            tenant_id=task_input.tenant_id,
            platform="claude_code",
            attempt=task_input.attempt,
        )
        try:
            emitter.emit_chunk("text", "hello world\n")
            ...
        finally:
            emitter.close()

    If ``chat_session_id`` is empty the emitter operates in no-op mode
    (every call returns immediately) — keeps the rollout-flag path
    cheap when streaming is disabled for a tenant.
    """

    def __init__(
        self,
        *,
        chat_session_id: str,
        tenant_id: str,
        platform: str,
        attempt: int = 1,
        api_base_url: Optional[str] = None,
        api_internal_key: Optional[str] = None,
        flush_ms: Optional[int] = None,
    ) -> None:
        self._sid = (chat_session_id or "").strip()
        self._tid = (tenant_id or "").strip()
        self._platform = platform
        self._attempt = int(attempt or 1)
        self._enabled = bool(self._sid)
        self._api_base_url = (
            api_base_url
            or os.environ.get("API_BASE_URL", "http://agentprovision-api")
        ).rstrip("/")
        self._api_key = api_internal_key or os.environ.get("API_INTERNAL_KEY", "")
        self._flush_ms = int(flush_ms if flush_ms is not None else _DEFAULT_FLUSH_MS)

        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._stop = threading.Event()
        self._lock = threading.Lock()  # protects counters
        self._dropped_total = 0
        self._dropped_by_kind: Dict[str, int] = {}
        self._emitted_total = 0
        self._batches_sent = 0
        self._http_errors = 0

        # httpx.Client connection re-use across batch posts.
        self._http: Optional[httpx.Client] = None
        if self._enabled:
            self._http = httpx.Client(timeout=2.0)
            self._thread = threading.Thread(
                target=self._run, name="SessionEventEmitter", daemon=True,
            )
            self._thread.start()
        else:
            self._thread = None

    # ------------------------------------------------------------------ public

    def emit_chunk(
        self,
        chunk_kind: str,
        chunk: str,
        *,
        fd: str = "stdout",
        raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue a chunk for the next flush window.

        Fail-soft: never raises, never blocks the producer (the queue
        is unbounded but the background flusher drains it; if the API
        is down the drop policy bounds memory growth).
        """
        if not self._enabled:
            return
        if not chunk:
            return

        item = {
            "chunk_kind": chunk_kind or "stdout",
            "chunk": chunk,
            "fd": fd or "stdout",
            "attempt": self._attempt,
            "ts_worker": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if raw is not None:
            try:
                import json as _json
                raw_str = _json.dumps(raw)
                if len(raw_str) <= 4096:  # cap at 4 KB per chunk
                    item["raw"] = raw
            except Exception:
                pass

        # Apply drop policy under back-pressure.
        if self._q.qsize() > _QUEUE_HIGH_WATER:
            kind = item["chunk_kind"]
            if kind not in _NEVER_DROP_KINDS and kind in _DROP_PRIORITY:
                self._record_drop(kind)
                return
            # If even the priority kinds are over budget but this chunk
            # is non-droppable, we still enqueue — overflow is logged
            # downstream when the HTTP fan-out drops the batch.

        self._q.put(item)

    def close(self, *, wait: bool = True, timeout: float = 5.0) -> Dict[str, int]:
        """Flush remaining chunks + tear down the background thread.

        Returns counters snapshot — useful for telemetry / tests.

        Close-race hardening (review I2): the background `_run` loop
        now owns the final drain. Calling `_flush_once` synchronously
        from `close()` while `_run` is mid-flight created a race over
        `self._http` — both threads could enter `_post_batch` and one
        would see `self._http` as None after the other called close().
        Instead, we just signal stop, let `_run` do one last drain
        pass on its way out, then close the http client ONCE the
        thread has joined.
        """
        if not self._enabled:
            return self._stats()
        self._stop.set()
        if wait and self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "SessionEventEmitter background thread did not exit cleanly "
                    "within %.1fs (sid=%s); proceeding with http close anyway",
                    timeout, self._sid,
                )
        # Only close the http client AFTER the background thread is
        # gone. If the thread is still alive (e.g. wait=False) we still
        # close — caller opted into that race.
        if self._http is not None:
            try:
                self._http.close()
            except Exception:  # noqa: BLE001
                pass
            self._http = None
        return self._stats()

    # ------------------------------------------------------------------ internal

    def _stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "emitted": self._emitted_total,
                "dropped": self._dropped_total,
                "batches": self._batches_sent,
                "http_errors": self._http_errors,
                **{f"dropped_{k}": v for k, v in self._dropped_by_kind.items()},
            }

    def _record_drop(self, kind: str) -> None:
        with self._lock:
            self._dropped_total += 1
            self._dropped_by_kind[kind] = self._dropped_by_kind.get(kind, 0) + 1
        # Throttle the log so a flooded session doesn't spam.
        if self._dropped_total % 100 == 1:
            logger.warning(
                "SessionEventEmitter dropping %s chunks (total=%d, by_kind=%s)",
                kind, self._dropped_total, self._dropped_by_kind,
            )

    def _run(self) -> None:
        """Background flusher loop. Wakes every `flush_ms` and posts
        whatever has accumulated.

        On `_stop`, drains the queue one final time so close() can rely
        on this thread (and only this thread) owning `self._http` —
        avoids the close-race fixed in review I2.
        """
        interval = max(0.01, self._flush_ms / 1000.0)
        while not self._stop.is_set():
            # `_stop.wait` returns True when set, False on timeout —
            # cleaner than time.sleep + recheck because close() unblocks
            # us immediately on shutdown.
            self._stop.wait(timeout=interval)
            self._flush_once()
        # Stop signalled — one last drain pass for anything queued
        # after the final scheduled flush.
        self._flush_once(force=True)

    def _flush_once(self, *, force: bool = False) -> None:
        """Drain queue → batch(es) → POST. Splits at chunk + byte caps."""
        batch: List[Dict[str, Any]] = []
        batch_bytes = 0
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            item_bytes = len(item.get("chunk", "")) + 64  # rough overhead
            if batch and (
                len(batch) >= _MAX_BATCH_CHUNKS
                or batch_bytes + item_bytes > _MAX_BATCH_BYTES
            ):
                # Flush before adding this one.
                self._post_batch(batch)
                batch = []
                batch_bytes = 0
            batch.append(item)
            batch_bytes += item_bytes
        if batch:
            self._post_batch(batch)
        # `force` is a hint for close()-time — currently the loop above
        # always drains everything queued. Kept for future expansion.
        _ = force

    def _post_batch(self, batch: List[Dict[str, Any]]) -> None:
        if not batch or self._http is None:
            return
        body = {
            "tenant_id": self._tid,
            "type": "cli_subprocess_stream",
            "payload": {
                "platform": self._platform,
                "batch": batch,
            },
        }
        url = f"{self._api_base_url}/api/v2/internal/sessions/{self._sid}/events"
        try:
            resp = self._http.post(
                url, json=body,
                headers={"X-Internal-Key": self._api_key or "dev_internal_key"},
            )
            if 200 <= resp.status_code < 300:
                with self._lock:
                    self._batches_sent += 1
                    self._emitted_total += len(batch)
            else:
                with self._lock:
                    self._http_errors += 1
                if self._http_errors < 3 or self._http_errors % 50 == 0:
                    logger.warning(
                        "SessionEventEmitter API non-2xx %s (sid=%s, dropping %d chunks)",
                        resp.status_code, self._sid, len(batch),
                    )
        except Exception as e:  # noqa: BLE001
            # Fail-soft. Subprocess output must NEVER block on emit.
            with self._lock:
                self._http_errors += 1
            if self._http_errors < 3 or self._http_errors % 50 == 0:
                logger.warning(
                    "SessionEventEmitter HTTP error %s (sid=%s, dropping %d chunks)",
                    e, self._sid, len(batch),
                )

    # ------------------------------------------------------------------ misc

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def attempt(self) -> int:
        return self._attempt
