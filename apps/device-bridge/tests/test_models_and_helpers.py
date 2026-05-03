"""Pydantic schema validation + RTSP URL builder tests."""
from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_camera_config_accepts_rtsp(main_module):
    cfg = main_module.CameraConfig(
        device_id="cam-1",
        name="Front",
        rtsp_url="rtsp://10.0.0.5:554/live",
    )
    assert cfg.rtsp_url == "rtsp://10.0.0.5:554/live"


def test_camera_config_accepts_rtsps(main_module):
    cfg = main_module.CameraConfig(
        device_id="cam-2",
        name="Back",
        rtsp_url="rtsps://10.0.0.5:322/live",
    )
    assert cfg.rtsp_url.startswith("rtsps://")


def test_camera_config_rejects_http_scheme(main_module):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        main_module.CameraConfig(
            device_id="cam-3",
            name="Bad",
            rtsp_url="http://10.0.0.5/stream",
        )
    assert "rtsp" in str(exc.value)


def test_camera_config_rejects_empty_scheme(main_module):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        main_module.CameraConfig(
            device_id="cam-4",
            name="Bad",
            rtsp_url="just-a-string",
        )


def test_build_authenticated_rtsp_no_credentials(main_module):
    out = main_module._build_authenticated_rtsp("rtsp://host:554/path", None, None)
    assert out == "rtsp://host:554/path"


def test_build_authenticated_rtsp_embeds_credentials(main_module):
    out = main_module._build_authenticated_rtsp(
        "rtsp://host:554/path", "admin", "p@ss/word"
    )
    # @ and / must be percent-encoded.
    assert "admin:p%40ss%2Fword@host:554" in out


def test_build_authenticated_rtsp_replaces_existing_userinfo(main_module):
    """If the URL already had credentials, they should be replaced (not duplicated)."""
    out = main_module._build_authenticated_rtsp(
        "rtsp://old:old@host:554/path", "new", "newpw"
    )
    assert "old:old" not in out
    assert "new:newpw@host:554" in out


def test_build_authenticated_rtsp_rejects_non_rtsp(main_module):
    with pytest.raises(HTTPException) as exc:
        main_module._build_authenticated_rtsp("http://host/x", None, None)
    assert exc.value.status_code == 422


def test_build_authenticated_rtsp_rejects_missing_host(main_module):
    with pytest.raises(HTTPException) as exc:
        main_module._build_authenticated_rtsp("rtsp:///nohost", None, None)
    assert exc.value.status_code == 422


def test_connect_request_accepts_minimal_payload(main_module):
    req = main_module.ConnectRequest(
        device_id="cam-1", sdp="v=0\r\n", type="offer"
    )
    assert req.device_id == "cam-1"
    assert req.type == "offer"
