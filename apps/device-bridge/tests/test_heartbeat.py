"""Heartbeat loop wiring tests — verify the startup task is scheduled and
that heartbeat_loop posts to the Luna API without crashing on httpx errors.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_startup_event_schedules_heartbeat(main_module):
    """`startup_event` should call `asyncio.create_task(heartbeat_loop())`."""
    sentinel = object()

    async def fake_loop():
        return None

    with patch.object(main_module, "heartbeat_loop", fake_loop), \
         patch.object(main_module.asyncio, "create_task", return_value=sentinel) as ct:
        await main_module.startup_event()
        assert ct.call_count == 1


@pytest.mark.asyncio
async def test_heartbeat_loop_posts_once_then_exits(main_module):
    """Drive heartbeat_loop through one iteration by making asyncio.sleep raise.

    This proves the POST is attempted with the device token header and that the
    URL is built from LUNA_API_URL + DEVICE_ID.
    """
    fake_resp = MagicMock(status_code=200)
    fake_client = MagicMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    class StopLoop(Exception):
        pass

    async def stop_after_first(_seconds):
        raise StopLoop()

    with patch.object(main_module.httpx, "AsyncClient", return_value=fake_client), \
         patch.object(main_module.asyncio, "sleep", side_effect=stop_after_first):
        with pytest.raises(StopLoop):
            await main_module.heartbeat_loop()

    assert fake_client.post.await_count == 1
    called_url = fake_client.post.await_args.args[0]
    assert called_url.endswith(f"/devices/{main_module.DEVICE_ID}/heartbeat")
    headers = fake_client.post.await_args.kwargs.get("headers", {})
    assert headers.get("X-Device-Token") == main_module.DEVICE_BRIDGE_TOKEN


@pytest.mark.asyncio
async def test_heartbeat_loop_swallows_http_errors(main_module):
    """A network error in one cycle must not kill the loop."""
    fake_client = MagicMock()
    fake_client.post = AsyncMock(side_effect=RuntimeError("network down"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    class StopLoop(Exception):
        pass

    sleeps = {"count": 0}

    async def stop_after_first(_seconds):
        sleeps["count"] += 1
        raise StopLoop()

    with patch.object(main_module.httpx, "AsyncClient", return_value=fake_client), \
         patch.object(main_module.asyncio, "sleep", side_effect=stop_after_first):
        with pytest.raises(StopLoop):
            await main_module.heartbeat_loop()

    # We reached the sleep() call after the failed POST, proving the except branch ran.
    assert sleeps["count"] == 1
    assert fake_client.post.await_count == 1
