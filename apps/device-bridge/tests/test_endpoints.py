"""Endpoint tests for /cameras, /bridge/connect, /status — with mocked aiortc."""
from __future__ import annotations

from unittest.mock import patch


def _add(client, payload, auth_headers):
    return client.post("/cameras", json=payload, headers=auth_headers)


def test_add_camera_persists_in_registry(client, sample_camera_payload, auth_headers, main_module):
    resp = _add(client, sample_camera_payload, auth_headers)
    assert resp.status_code == 200
    assert "cam-1" in main_module.cameras
    assert main_module.cameras["cam-1"]["status"] == "idle"
    assert main_module.cameras["cam-1"]["config"].name == "Front Door"


def test_add_camera_rejects_invalid_rtsp(client, auth_headers):
    bad = {
        "device_id": "cam-x",
        "name": "Bad",
        "rtsp_url": "http://not-rtsp.example/stream",
    }
    resp = client.post("/cameras", json=bad, headers=auth_headers)
    # Pydantic v2 returns 422 for validation errors.
    assert resp.status_code == 422


def test_status_reflects_added_cameras(client, sample_camera_payload, auth_headers):
    _add(client, sample_camera_payload, auth_headers)
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["camera_count"] == 1
    assert body["active_connections"] == 0
    assert body["bridge_name"]
    assert body["bridge_id"]


def test_connect_unknown_camera_returns_404(client, auth_headers):
    resp = client.post(
        "/bridge/connect",
        headers=auth_headers,
        json={"device_id": "missing", "sdp": "v=0\r\n", "type": "offer"},
    )
    assert resp.status_code == 404


def test_connect_happy_path_returns_answer(
    client, sample_camera_payload, auth_headers, main_module, mock_rtc
):
    """Mocks RTCPeerConnection + MediaPlayer, asserts answer returned and pc registered."""
    _add(client, sample_camera_payload, auth_headers)

    resp = client.post(
        "/bridge/connect",
        headers=auth_headers,
        json={"device_id": "cam-1", "sdp": "v=0\r\noffer-sdp", "type": "offer"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "answer"
    assert body["sdp"].startswith("v=0")

    # PC was constructed and registered in the global set.
    assert mock_rtc.call_count == 1
    assert len(main_module.pcs) == 1


def test_connect_uses_authenticated_rtsp_url(
    client, sample_camera_payload, auth_headers, main_module, mock_rtc
):
    """Verify the MediaPlayer is invoked with credentials baked into the URL."""
    _add(client, sample_camera_payload, auth_headers)

    with patch.object(main_module, "MediaPlayer") as player_cls:
        player_cls.return_value.video = object()  # truthy track
        resp = client.post(
            "/bridge/connect",
            headers=auth_headers,
            json={"device_id": "cam-1", "sdp": "v=0\r\n", "type": "offer"},
        )
        assert resp.status_code == 200
        called_url = player_cls.call_args[0][0]
        assert called_url.startswith("rtsp://admin:")
        assert "@192.168.1.10:554" in called_url


def test_connect_handles_player_failure(
    client, sample_camera_payload, auth_headers, main_module
):
    """If MediaPlayer raises, endpoint returns 500 and the pc is cleaned up."""
    _add(client, sample_camera_payload, auth_headers)

    with patch.object(main_module, "MediaPlayer", side_effect=RuntimeError("rtsp boom")), \
         patch.object(main_module, "RTCPeerConnection") as pc_cls:
        from unittest.mock import AsyncMock, MagicMock

        pc = MagicMock()
        pc.close = AsyncMock()
        pc.on = MagicMock(side_effect=lambda evt: (lambda fn: fn))
        pc_cls.return_value = pc

        resp = client.post(
            "/bridge/connect",
            headers=auth_headers,
            json={"device_id": "cam-1", "sdp": "v=0\r\n", "type": "offer"},
        )
        assert resp.status_code == 500
        # pc should have been closed and removed.
        assert pc.close.await_count >= 1
        assert len(main_module.pcs) == 0


def test_snapshot_unknown_camera_returns_404(client, auth_headers):
    resp = client.post("/cameras/nope/snapshot", headers=auth_headers)
    assert resp.status_code == 404


def test_snapshot_without_cv2_returns_501(
    client, sample_camera_payload, auth_headers, main_module
):
    """Simulate cv2 not installed by making the import inside the handler raise."""
    _add(client, sample_camera_payload, auth_headers)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("no cv2 in this env")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        resp = client.post("/cameras/cam-1/snapshot", headers=auth_headers)

    assert resp.status_code == 501
    assert "cv2" in resp.json()["detail"]


def test_snapshot_happy_path(
    client, sample_camera_payload, auth_headers, main_module
):
    """Inject a fake cv2 module returning a one-pixel frame."""
    import sys
    import types
    from unittest.mock import MagicMock

    fake_cv2 = types.ModuleType("cv2")
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (True, b"fake-frame-bytes")
    fake_cap.release = MagicMock()
    fake_cv2.VideoCapture = MagicMock(return_value=fake_cap)  # type: ignore[attr-defined]
    fake_cv2.imencode = MagicMock(return_value=(True, b"\xff\xd8\xff\xd9"))  # type: ignore[attr-defined]

    _add(client, sample_camera_payload, auth_headers)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        resp = client.post("/cameras/cam-1/snapshot", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["device_id"] == "cam-1"
    assert "image_b64" in body and body["image_b64"]
    assert "timestamp" in body


def test_snapshot_open_failure_returns_502(
    client, sample_camera_payload, auth_headers, main_module
):
    import sys
    import types
    from unittest.mock import MagicMock

    fake_cv2 = types.ModuleType("cv2")
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = False
    fake_cap.release = MagicMock()
    fake_cv2.VideoCapture = MagicMock(return_value=fake_cap)  # type: ignore[attr-defined]
    fake_cv2.imencode = MagicMock()  # type: ignore[attr-defined]

    _add(client, sample_camera_payload, auth_headers)

    with patch.dict(sys.modules, {"cv2": fake_cv2}):
        resp = client.post("/cameras/cam-1/snapshot", headers=auth_headers)

    assert resp.status_code == 502
    fake_cap.release.assert_called_once()
