"""Tests for the chat-turn thread-pool wedge fix (task #11, 2026-06-04).

Covers Luna's required test matrix (review 2):
  * Part-A real-timeout releases the worker thread (the shutdown(wait=True)
    foot-gun regression) — a never-returning dispatch must NOT hang.
  * WhatsApp capacity gate — per-sender AND global over-cap reject + fallback.
  * Per-sender ordering — same-sender turns run serially, in order.
  * Two different senders proceed under the global cap.
  * Consumer-map GC — maps clean up after the queue drains.
  * Submit-failure-during-shutdown terminalizes the job + sends a fallback.
  * Drain-deadline best-effort restart notice to pending + active senders.
  * run_job_blocking ownership guard + chunk concatenation.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from app.services import whatsapp_service as wa
from app.services.whatsapp_service import WhatsAppService, _WaChatTurn


# ───────────────────────────── helpers ──────────────────────────────


def _bare_service() -> WhatsAppService:
    """A WhatsAppService with ONLY the fire-and-forget dispatch state wired,
    bypassing __init__ (no DB / neonize). Enough for the orchestration tests.
    """
    from concurrent.futures import ThreadPoolExecutor

    svc = WhatsAppService.__new__(WhatsAppService)
    svc._chat_queues = {}
    svc._chat_consumers = {}
    svc._chat_active = {}
    svc._chat_inflight_global = 0
    svc._chat_dispatch_lock = asyncio.Lock()
    svc._chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wa-chat-test")
    svc._clients = {}
    svc._sent_message_ids = {}
    svc._inflight_turns = 0
    svc._draining = False
    return svc


def _turn(queue_key: str = "t:default::123", content: str = "hi") -> _WaChatTurn:
    return _WaChatTurn(
        queue_key=queue_key,
        account_key="t:default",
        tenant_id=uuid.uuid4(),
        tenant_id_str="t",
        account_id="default",
        sender_phone="123",
        reply_jid=object(),
        job_uuid=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content=content,
    )


async def _drain_idle(svc: WhatsAppService, timeout: float = 5.0) -> None:
    """Wait until all consumers exit and no turn is active."""
    t0 = time.monotonic()
    while (svc._chat_consumers or svc._chat_active) and time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.01)


# ───────────────────────── Part A: foot-gun ──────────────────────────


async def test_part_a_bounded_wait_releases_thread():
    """The dispatch pattern (asyncio.wait_for INSIDE the coroutine, run via a
    `with ThreadPoolExecutor`) must release the worker thread on timeout so the
    context-manager's shutdown(wait=True) returns promptly — NOT join a hung
    thread (the C1 foot-gun Luna caught). Old pattern would block ~3600s here.
    """
    import concurrent.futures

    async def _run_workflow():
        async def _never():
            await asyncio.sleep(3600)

        # The bound lives on the await itself — the coroutine self-terminates,
        # so asyncio.run() below returns (by raising) and the thread finishes.
        return await asyncio.wait_for(_never(), timeout=0.2)

    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(asyncio.TimeoutError):
            pool.submit(lambda: asyncio.run(_run_workflow())).result(timeout=5)
    # `with` exit ran shutdown(wait=True); it returned fast because the worker
    # thread already finished. The old foot-gun would hang on the 3600s sleep.
    assert time.monotonic() - t0 < 3.0


# ─────────────────────── capacity gate (over-cap) ────────────────────


async def test_enqueue_rejects_over_per_sender_cap(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_PER_SENDER_CAP", 2)
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_GLOBAL_CAP", 100)

    failed, overloaded = [], []
    monkeypatch.setattr(svc, "_fail_job_safe", lambda turn, err: failed.append(turn.job_uuid))

    async def _send_text(account_key, reply_jid, text):
        overloaded.append(text)

    monkeypatch.setattr(svc, "_send_text", _send_text)

    # Block the consumer from draining so the queue actually fills.
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_run_turn(turn):
        started.set()
        await release.wait()

    monkeypatch.setattr(svc, "_run_turn", _slow_run_turn)

    qk = "t:default::123"
    await svc._enqueue_turn(_turn(qk, "a"))   # consumer dequeues it + blocks
    await started.wait()                       # 'a' now in-flight, queue empty
    await svc._enqueue_turn(_turn(qk, "b"))   # queued (qsize 0→1 < cap 2)
    await svc._enqueue_turn(_turn(qk, "c"))   # queued (qsize 1→2 == cap)
    await svc._enqueue_turn(_turn(qk, "d"))   # qsize 2, not < 2 → REJECT

    assert len(failed) == 1                    # only 'd' was rejected
    assert overloaded == [wa.WHATSAPP_OVERLOADED_FALLBACK]
    release.set()
    await _drain_idle(svc)


async def test_enqueue_rejects_over_global_cap(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_GLOBAL_CAP", 1)
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_PER_SENDER_CAP", 100)

    failed, overloaded = [], []
    monkeypatch.setattr(svc, "_fail_job_safe", lambda turn, err: failed.append(turn.job_uuid))

    async def _send_text(account_key, reply_jid, text):
        overloaded.append(text)

    monkeypatch.setattr(svc, "_send_text", _send_text)

    release = asyncio.Event()

    async def _slow_run_turn(turn):
        await release.wait()

    monkeypatch.setattr(svc, "_run_turn", _slow_run_turn)

    await svc._enqueue_turn(_turn("t:default::A", "a"))   # accepted (global=1)
    await svc._enqueue_turn(_turn("t:default::B", "b"))   # different sender, global cap → REJECT

    assert len(failed) == 1
    assert overloaded == [wa.WHATSAPP_OVERLOADED_FALLBACK]
    release.set()
    await _drain_idle(svc)


# ────────────────────────── ordering ─────────────────────────────────


async def test_same_sender_turns_run_serially_in_order(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_GLOBAL_CAP", 100)
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_PER_SENDER_CAP", 100)

    order, concurrent_peak = [], {"running": 0, "max": 0}

    async def _run_turn(turn):
        concurrent_peak["running"] += 1
        concurrent_peak["max"] = max(concurrent_peak["max"], concurrent_peak["running"])
        await asyncio.sleep(0.02)
        order.append(turn.content)
        concurrent_peak["running"] -= 1

    monkeypatch.setattr(svc, "_run_turn", _run_turn)

    qk = "t:default::123"
    for c in ("a", "b", "c"):
        await svc._enqueue_turn(_turn(qk, c))
    await _drain_idle(svc)

    assert order == ["a", "b", "c"]      # in order
    assert concurrent_peak["max"] == 1   # strictly serial per sender


async def test_two_senders_proceed_concurrently(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_GLOBAL_CAP", 100)
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_PER_SENDER_CAP", 100)

    done = []

    async def _run_turn(turn):
        await asyncio.sleep(0.02)
        done.append(turn.queue_key)

    monkeypatch.setattr(svc, "_run_turn", _run_turn)

    await svc._enqueue_turn(_turn("t:default::A", "a"))
    await svc._enqueue_turn(_turn("t:default::B", "b"))
    # Two distinct consumers run.
    assert len([k for k in svc._chat_consumers]) == 2
    await _drain_idle(svc)
    assert set(done) == {"t:default::A", "t:default::B"}
    assert svc._chat_inflight_global == 0


# ─────────────────────── consumer-map GC ─────────────────────────────


async def test_consumer_map_gc_after_drain(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_GLOBAL_CAP", 100)
    monkeypatch.setattr(wa, "WHATSAPP_CHAT_PER_SENDER_CAP", 100)

    async def _run_turn(turn):
        await asyncio.sleep(0)

    monkeypatch.setattr(svc, "_run_turn", _run_turn)

    await svc._enqueue_turn(_turn("t:default::Z", "z"))
    await _drain_idle(svc)

    assert svc._chat_queues == {}
    assert svc._chat_consumers == {}
    assert svc._chat_active == {}
    assert svc._chat_inflight_global == 0


# ─────────────────── submit-failure during shutdown ──────────────────


async def test_run_turn_submit_failure_terminalizes_and_falls_back(monkeypatch):
    svc = _bare_service()
    svc._chat_executor.shutdown()  # any run_in_executor now raises RuntimeError

    failed, sends = [], []
    monkeypatch.setattr(svc, "_fail_job_safe", lambda turn, err: failed.append(err))

    async def _keep_typing(*a, **k):
        return

    async def _send_reply_or_fallback(turn, reply, ok):
        sends.append((reply, ok))

    monkeypatch.setattr(svc, "_keep_typing", _keep_typing)
    monkeypatch.setattr(svc, "_send_reply_or_fallback", _send_reply_or_fallback)

    await svc._run_turn(_turn())

    assert failed and "executor unavailable" in failed[0]
    assert sends == [(None, False)]            # fallback path
    assert svc._inflight_turns == 0            # bracket released


# ─────────────────────── drain notice ────────────────────────────────


async def test_drain_chat_consumers_notifies_and_cancels(monkeypatch):
    svc = _bare_service()
    notices = []

    async def _send_text(account_key, reply_jid, text):
        notices.append((account_key, text))

    monkeypatch.setattr(svc, "_send_text", _send_text)

    # One pending (queued) sender + one active (mid-flight) sender.
    q = asyncio.Queue()
    pending = _turn("t:default::PENDING", "p")
    q.put_nowait(pending)
    svc._chat_queues["t:default::PENDING"] = q

    async def _idle():
        await asyncio.sleep(60)

    cons = asyncio.create_task(_idle())
    svc._chat_consumers["t:default::PENDING"] = cons
    active = _turn("t:default::ACTIVE", "a")
    svc._chat_active["t:default::ACTIVE"] = active

    await svc._drain_chat_consumers()
    await asyncio.sleep(0.05)                   # let the cancellation propagate

    texts = {t for _, t in notices}
    keys = {k for k, _ in notices}
    assert texts == {wa.WHATSAPP_RESTART_FALLBACK}
    assert keys == {"t:default"}               # both senders share the account key
    assert len(notices) == 2                   # one per distinct queue_key
    assert cons.cancelled() or cons.done()
    assert svc._chat_queues == {} and svc._chat_consumers == {}


# ─────────────── run_job_blocking ownership + concat ─────────────────


def test_run_job_blocking_skips_when_not_owned(monkeypatch):
    """If start_job loses the queued→running race (returns False), the body is
    skipped — post_user_message is NOT called (Luna R4 ownership)."""
    from app.services import chat_jobs

    class _DummySession:
        def close(self):
            pass

    monkeypatch.setattr("app.db.session.SessionLocal", lambda: _DummySession())
    monkeypatch.setattr(chat_jobs, "start_job", lambda db, *, job_id: False)

    called = {"post": 0}

    def _post(*a, **k):
        called["post"] += 1
        return (object(), object())

    monkeypatch.setattr("app.services.chat.post_user_message", _post)

    chat_jobs.run_job_blocking(
        uuid.uuid4(),
        session_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        content="hi",
    )
    assert called["post"] == 0


def test_reply_text_from_events_concatenates_chunks(monkeypatch):
    from app.services import chat_jobs

    monkeypatch.setattr(
        chat_jobs, "read_events",
        lambda db, *, job_id, from_seq=0: [
            {"seq": 1, "kind": "lifecycle", "payload": {"event": "started"}},
            {"seq": 2, "kind": "chunk", "payload": {"text": "Hello "}},
            {"seq": 3, "kind": "chunk", "payload": {"text": "world"}},
            {"seq": 4, "kind": "lifecycle", "payload": {"event": "done"}},
        ],
    )
    assert chat_jobs.reply_text_from_events(None, job_id=uuid.uuid4()) == "Hello world"
