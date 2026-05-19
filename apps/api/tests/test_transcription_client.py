"""Tests for the api-side transcription client.

These exercise the bits that were silently broken before this PR:

* The Temporal client cache used a try/except NameError that was dead code
  (the module-level ``_client = None`` made the name always defined). Every
  caller got back ``None`` and exploded on ``.start_workflow``.
* The workflow dispatch path was therefore never exercised end-to-end in
  the prior pytest suite. We add the test coverage now so a regression to
  the broken cache pattern would surface immediately.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Test helpers ───────────────────────────────────────────────────────────


def _install_fake_temporalio(monkeypatch, mock_connect: AsyncMock) -> MagicMock:
    """Install a stub temporalio.client module with a mock Client.connect.

    Returns the MagicMock that stands in for the connected client so the
    test can assert on .start_workflow / .get_workflow_handle calls.
    """
    mock_client = MagicMock(name="TemporalClient")
    mock_client.start_workflow = AsyncMock(name="start_workflow")
    mock_client.get_workflow_handle = MagicMock(name="get_workflow_handle")

    # Client.connect must be a coroutine returning the mock client.
    mock_connect.return_value = mock_client

    # Build a stub module so `from temporalio.client import Client` works.
    fake_temporalio = types.ModuleType("temporalio")
    fake_client_mod = types.ModuleType("temporalio.client")
    fake_client_mod.Client = MagicMock()
    fake_client_mod.Client.connect = mock_connect

    fake_common_mod = types.ModuleType("temporalio.common")

    class _RetryPolicy:
        def __init__(self, *_args, **_kwargs):
            pass

    fake_common_mod.RetryPolicy = _RetryPolicy

    monkeypatch.setitem(sys.modules, "temporalio", fake_temporalio)
    monkeypatch.setitem(sys.modules, "temporalio.client", fake_client_mod)
    monkeypatch.setitem(sys.modules, "temporalio.common", fake_common_mod)

    return mock_client


def _reset_transcription_client_singleton():
    """Clear the module-level _client so each test starts cold."""
    from app.services import transcription_client as tc

    tc._client = None


# ── _get_client cache ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_client_caches_connection(monkeypatch, tmp_path):
    """First call connects, subsequent calls reuse the cached client."""
    _reset_transcription_client_singleton()
    mock_connect = AsyncMock(name="Client.connect")
    _install_fake_temporalio(monkeypatch, mock_connect)

    from app.services import transcription_client as tc

    client1 = await tc._get_client()
    client2 = await tc._get_client()

    assert client1 is client2, "expected the same cached client instance"
    assert mock_connect.await_count == 1, (
        f"Client.connect should run exactly once, got {mock_connect.await_count}"
    )


@pytest.mark.asyncio
async def test_get_client_concurrent_first_callers_run_connect_once(
    monkeypatch,
):
    """Concurrent first-callers serialise on the lock — connect runs once."""
    _reset_transcription_client_singleton()
    mock_connect = AsyncMock(name="Client.connect")
    _install_fake_temporalio(monkeypatch, mock_connect)

    from app.services import transcription_client as tc

    # Reset the lock too so an earlier test's lock state can't leak.
    tc._client_lock = asyncio.Lock()

    results = await asyncio.gather(
        tc._get_client(), tc._get_client(), tc._get_client()
    )
    assert all(r is results[0] for r in results)
    assert mock_connect.await_count == 1


# ── _start_workflow ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_workflow_dispatches_with_expected_id(monkeypatch):
    """The workflow id format is `transcribe-<hex>` and the payload is correct."""
    _reset_transcription_client_singleton()
    mock_connect = AsyncMock(name="Client.connect")
    mock_client = _install_fake_temporalio(monkeypatch, mock_connect)

    from app.services import transcription_client as tc

    tc._client_lock = asyncio.Lock()

    workflow_id = await tc._start_workflow("/tmp/audio.bin")

    assert workflow_id.startswith("transcribe-"), workflow_id
    # 'transcribe-' + 32 hex chars
    assert len(workflow_id) == len("transcribe-") + 32

    assert mock_client.start_workflow.await_count == 1
    args, kwargs = mock_client.start_workflow.call_args
    # First positional arg is the workflow name.
    assert args[0] == "TranscribeAudioWorkflow"
    # Second positional arg is the payload dict.
    payload = args[1]
    assert payload["audio_path"] == "/tmp/audio.bin"
    assert payload["delete_after"] is True
    # kwargs carry the workflow id + task queue
    assert kwargs["id"] == workflow_id
    assert kwargs["task_queue"] == "agentprovision-code"


# ── transcribe_async happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcribe_async_completes_inline(monkeypatch, tmp_path):
    """End-to-end async dispatch: write → start → await result returns a transcript."""
    _reset_transcription_client_singleton()
    mock_connect = AsyncMock(name="Client.connect")
    mock_client = _install_fake_temporalio(monkeypatch, mock_connect)

    from app.services import transcription_client as tc

    tc._client_lock = asyncio.Lock()

    # Steer the shared-volume write into the test's tmp dir.
    monkeypatch.setattr(tc, "_TRANSCRIBE_DIR", str(tmp_path))

    # Workflow handle returns a completed dict.
    handle = MagicMock()
    handle.result = AsyncMock(
        return_value={
            "transcript": "hello world",
            "engine": "whisper-local",
            "duration_ms": 1234,
        }
    )
    mock_client.get_workflow_handle.return_value = handle

    result = await tc.transcribe_async(b"fake audio bytes", sync_timeout=0.5)

    assert result.transcript == "hello world"
    assert result.engine == "whisper-local"
    assert result.duration_ms == 1234
    assert result.status == "completed"
    assert mock_client.start_workflow.await_count == 1

    # And calling again does NOT re-connect (cache is alive).
    handle.result = AsyncMock(
        return_value={"transcript": "second", "engine": "whisper-local", "duration_ms": 100}
    )
    second = await tc.transcribe_async(b"more audio", sync_timeout=0.5)
    assert second.transcript == "second"
    assert mock_connect.await_count == 1, "Client.connect must only run once total"
