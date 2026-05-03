"""Smoke tests for worker.py — the Temporal worker entrypoint.

worker.py is mostly a wiring file. We only cover that:
  1. The module imports cleanly with our test env.
  2. Constants (TEMPORAL_ADDRESS, TASK_QUEUE) resolve to the expected values.
  3. ``main()`` connects to Temporal and starts a worker on the right queue.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def test_module_imports_cleanly():
    import worker  # noqa: F401


def test_task_queue_constant():
    import worker
    assert worker.TASK_QUEUE == "agentprovision-code"


def test_temporal_address_resolved_from_env():
    import worker
    assert worker.TEMPORAL_ADDRESS  # set via conftest setdefault


@pytest.mark.asyncio
async def test_main_connects_and_runs(monkeypatch):
    import worker

    fake_client = MagicMock(name="client")
    fake_worker = MagicMock(name="worker")
    fake_worker.run = AsyncMock(return_value=None)

    connect = AsyncMock(return_value=fake_client)
    monkeypatch.setattr(worker.Client, "connect", connect)

    captured: dict = {}

    def fake_worker_ctor(client, **kwargs):
        captured["client"] = client
        captured["kwargs"] = kwargs
        return fake_worker

    monkeypatch.setattr(worker, "Worker", fake_worker_ctor)

    await worker.main()

    connect.assert_awaited_once_with("temporal:7233")
    assert captured["client"] is fake_client
    assert captured["kwargs"]["task_queue"] == "agentprovision-code"
    # The worker must register both workflows + the chat-cli activity.
    workflows_registered = captured["kwargs"]["workflows"]
    assert worker.CodeTaskWorkflow in workflows_registered
    assert worker.ChatCliWorkflow in workflows_registered
    activities_registered = captured["kwargs"]["activities"]
    assert worker.execute_chat_cli in activities_registered
    fake_worker.run.assert_awaited_once()
