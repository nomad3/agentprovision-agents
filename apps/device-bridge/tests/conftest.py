"""Shared fixtures for device-bridge tests.

Important: env vars must be set before importing `main` because the module
captures them at import time (DEVICE_BRIDGE_TOKEN, LUNA_API_URL, etc.).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make `apps/device-bridge` importable as the cwd so `import main` works.
APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Set required env BEFORE importing main.
TEST_TOKEN = "test-token-32bytes-1234567890ab"
os.environ.setdefault("DEVICE_BRIDGE_TOKEN", TEST_TOKEN)
os.environ.setdefault("LUNA_API_URL", "http://luna-api/api/v1")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture
def main_module():
    """Import main fresh each test and reset module-level state."""
    import main  # type: ignore

    # Ensure token matches test expectations even if a prior test mutated it.
    main.DEVICE_BRIDGE_TOKEN = TEST_TOKEN
    main.cameras.clear()
    main.pcs.clear()
    yield main
    main.cameras.clear()
    main.pcs.clear()


@pytest.fixture
def client(main_module):
    """Sync FastAPI TestClient.

    Patches the startup event so `asyncio.create_task(heartbeat_loop())`
    does not actually fire while the TestClient lifespan runs.
    """
    from fastapi.testclient import TestClient

    # Replace heartbeat_loop with a no-op coroutine so startup is safe.
    async def _noop_heartbeat():
        return None

    with patch.object(main_module, "heartbeat_loop", _noop_heartbeat):
        with TestClient(main_module.app) as c:
            yield c


@pytest.fixture
def auth_headers() -> dict:
    return {"X-Bridge-Token": TEST_TOKEN}


@pytest.fixture
def sample_camera_payload() -> dict:
    return {
        "device_id": "cam-1",
        "name": "Front Door",
        "rtsp_url": "rtsp://192.168.1.10:554/live",
        "username": "admin",
        "password": "p@ss/word",
    }


@pytest.fixture
def mock_rtc(main_module) -> Iterator[MagicMock]:
    """Patch RTCPeerConnection + MediaPlayer so no real network/codec work happens.

    Returns the mocked PeerConnection class. Each call to it returns a fresh
    AsyncMock-laden instance whose createAnswer returns a stub SDP.
    """
    fake_local_desc = MagicMock()
    fake_local_desc.sdp = "v=0\r\n...stub-answer-sdp..."
    fake_local_desc.type = "answer"

    def _make_pc():
        pc = MagicMock(name="PeerConnection")
        pc.connectionState = "new"
        pc.setRemoteDescription = AsyncMock()
        pc.createAnswer = AsyncMock(return_value=MagicMock())
        pc.setLocalDescription = AsyncMock()
        pc.close = AsyncMock()
        pc.addTrack = MagicMock()
        # decorator-style on(...) -> returns the function passed in
        pc.on = MagicMock(side_effect=lambda event: (lambda fn: fn))
        pc.localDescription = fake_local_desc
        return pc

    pc_factory = MagicMock(side_effect=_make_pc)

    fake_player = MagicMock(name="MediaPlayer")
    fake_player.video = MagicMock()
    player_factory = MagicMock(return_value=fake_player)

    with patch.object(main_module, "RTCPeerConnection", pc_factory), \
         patch.object(main_module, "MediaPlayer", player_factory):
        yield pc_factory
