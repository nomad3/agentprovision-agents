"""T6.4d — WhatsApp → LearningService integration test.

Spec §7 + plan T4.2: when a WhatsApp inbound message text contains a
recognized learning URL (YouTube / IG), the system must:

  1. ``_detect_inbound_media`` returns the new ``("learning_url",
     url, caption)`` tuple variant (NOT mis-classifying it as audio
     / document / etc.).
  2. ``LearningService.dispatch`` is invoked with a ``LearningIntent``
     whose ``source_url`` is the detected URL.
  3. A workflow id is returned by the dispatch (fire-and-forget — the
     workflow notifies Luna's chat session when it terminates).

This test mocks the Temporal client end so it doesn't require a
running temporal-server; the workflow body is not executed. The
contract under test is **the handoff** between the WhatsApp detector
and the LearningService dispatch surface — the two pieces that have
to agree on the tuple shape + intent payload field names. A drift
between them would silently break every WhatsApp-originated learn
request without any test failing today, which is the gap T6.4d
closes.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "True")


# ── Helpers — build a minimal neonize-style protobuf-ish msg ────────────


def _make_msg_with_text(text: str):
    """Build a SimpleNamespace shaped like neonize's Message proto.

    `_detect_inbound_media` reads `getattr(msg, "imageMessage", None)`,
    `audioMessage`, `documentMessage`. We populate them with empty
    sub-namespaces (no mimetype) so the audio/image/document branches
    don't fire and the URL-extraction fallback runs.
    """
    # Empty sub-messages: image / audio / document with NO attachment
    # fields → the existing detector requires at least one payload
    # field to consider them real (see whatsapp_service.py:70).
    return SimpleNamespace(
        imageMessage=SimpleNamespace(mimetype=None),
        audioMessage=SimpleNamespace(
            mimetype=None, fileLength=0, mediaKey=b"", directPath=""
        ),
        documentMessage=SimpleNamespace(mimetype=None),
    )


# ── 1) detector returns the learning_url tuple variant ──────────────────


def test_detect_inbound_media_returns_learning_url_for_youtube():
    """An inbound text containing a YouTube URL must classify as
    ``learning_url`` with the URL as the ``media_mime`` slot and the
    original text as the caption. The downstream pipeline depends on
    this exact tuple shape per spec §7 + plan T4.2."""
    from app.services.whatsapp_service import _detect_inbound_media

    text = "hey baby learn this: https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    msg = _make_msg_with_text(text)

    media_type, media_mime, media_caption = _detect_inbound_media(msg, text)

    assert media_type == "learning_url"
    assert media_mime == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert media_caption == text


def test_detect_inbound_media_returns_learning_url_for_youtu_be():
    """Short youtu.be links must trip the same branch (spec §7)."""
    from app.services.whatsapp_service import _detect_inbound_media

    text = "watch https://youtu.be/dQw4w9WgXcQ"
    msg = _make_msg_with_text(text)

    media_type, media_mime, media_caption = _detect_inbound_media(msg, text)

    assert media_type == "learning_url"
    assert media_mime == "https://youtu.be/dQw4w9WgXcQ"


def test_detect_inbound_media_returns_learning_url_for_instagram():
    """Instagram reel + post links trip the same branch (spec §7)."""
    from app.services.whatsapp_service import _detect_inbound_media

    text = "check out this reel: https://www.instagram.com/reel/AbCdEfGh"
    msg = _make_msg_with_text(text)

    media_type, media_mime, media_caption = _detect_inbound_media(msg, text)

    assert media_type == "learning_url"
    assert media_mime.startswith("https://www.instagram.com/reel/")


def test_detect_inbound_media_no_url_returns_none():
    """Plain-text messages with no learning URL must fall through to
    ``(None, None, text)`` — the existing chat path. If this regresses
    every text message routes into the learning pipeline by accident."""
    from app.services.whatsapp_service import _detect_inbound_media

    text = "hey can you tell me about my calendar today"
    msg = _make_msg_with_text(text)

    media_type, media_mime, media_caption = _detect_inbound_media(msg, text)

    assert media_type is None
    assert media_mime is None
    assert media_caption == text


# ── 2) LearningService.dispatch handoff ─────────────────────────────────


async def test_learning_service_dispatch_invokes_start_workflow():
    """The handoff: when `_detect_inbound_media` returns a
    ``learning_url`` tuple, the WhatsApp router constructs a
    ``LearningIntent`` and awaits ``LearningService.dispatch``. We
    mock the Temporal client so the workflow body isn't executed
    — only the dispatch contract (workflow name, payload, task queue)
    is asserted.

    Mirrors the verification path used by
    ``test_review_dispatch.py::test_dispatch_review_workflow_awaits_start_workflow``.
    """
    from app.services.learning_service import LearningService
    from app.schemas.learning import LearningIntent

    intent = LearningIntent(
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        tenant_id="00000000-0000-0000-0000-000000000001",
        actor_user_id="00000000-0000-0000-0000-0000000000aa",
    )

    recorded: list[dict] = []

    async def _record_start_workflow(*args, **kwargs):
        recorded.append({"args": args, "kwargs": kwargs})
        return MagicMock()

    fake_client = AsyncMock()
    fake_client.start_workflow = _record_start_workflow

    async def _fake_connect(*_a, **_kw):
        return fake_client

    with patch("temporalio.client.Client.connect", _fake_connect):
        workflow_id = await LearningService.dispatch(intent)

    # Exactly one start_workflow invocation with the right shape.
    assert len(recorded) == 1
    call = recorded[0]
    assert call["args"][0] == "LearnFromMediaWorkflow"
    # Payload is the LearningIntent model_dump — must echo the URL the
    # detector handed off.
    payload = call["args"][1]
    assert payload["source_url"] == intent.source_url
    assert payload["tenant_id"] == intent.tenant_id
    assert payload["actor_user_id"] == intent.actor_user_id
    # Task queue convention — single orchestration queue.
    assert call["kwargs"]["task_queue"] == "agentprovision-orchestration"
    # Workflow id is tenant-prefixed (per the service's contract).
    assert workflow_id.startswith(f"luna-learn-{intent.tenant_id}-")
    # And the id passed via `id=` kwarg matches the returned value.
    assert call["kwargs"]["id"] == workflow_id


# ── 3) Detector → service tuple-to-intent compatibility ─────────────────


async def test_detector_tuple_is_valid_input_for_learning_intent():
    """End-to-end shape compatibility: the URL slot returned by
    ``_detect_inbound_media`` must be a valid ``source_url`` for the
    ``LearningIntent`` model. If a future refactor changes the
    detector's tuple field order, this test catches the silent break
    even when the WhatsApp router glue lives in another module."""
    from app.services.whatsapp_service import _detect_inbound_media
    from app.schemas.learning import LearningIntent

    text = "https://youtu.be/dQw4w9WgXcQ"
    msg = _make_msg_with_text(text)
    media_type, media_mime, _caption = _detect_inbound_media(msg, text)

    assert media_type == "learning_url"
    # Slot 2 (media_mime) carries the URL when media_type == "learning_url"
    # — this is the contract documented in whatsapp_service.py:105.
    intent = LearningIntent(
        source_url=media_mime,
        tenant_id="00000000-0000-0000-0000-000000000001",
        actor_user_id="00000000-0000-0000-0000-0000000000aa",
    )
    assert intent.source_url == "https://youtu.be/dQw4w9WgXcQ"
