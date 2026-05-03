"""Token-guard tests for /cameras, /cameras/{id}/snapshot, /bridge/connect."""
from __future__ import annotations


def test_status_endpoint_is_public(client):
    """Status is unauthenticated — used for liveness/readiness checks."""
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["camera_count"] == 0
    assert body["active_connections"] == 0
    assert body["configured"] is True


def test_add_camera_rejects_missing_token(client, sample_camera_payload):
    resp = client.post("/cameras", json=sample_camera_payload)
    # FastAPI returns 401 from our HTTPException for missing/invalid token.
    assert resp.status_code == 401
    assert "Invalid bridge token" in resp.json()["detail"]


def test_add_camera_rejects_wrong_token(client, sample_camera_payload):
    resp = client.post(
        "/cameras",
        json=sample_camera_payload,
        headers={"X-Bridge-Token": "definitely-not-the-token"},
    )
    assert resp.status_code == 401


def test_add_camera_accepts_x_bridge_token(client, sample_camera_payload, auth_headers):
    resp = client.post("/cameras", json=sample_camera_payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "added", "device_id": "cam-1"}


def test_add_camera_accepts_bearer_authorization(client, sample_camera_payload):
    from tests.conftest import TEST_TOKEN

    resp = client.post(
        "/cameras",
        json=sample_camera_payload,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    assert resp.status_code == 200


def test_unconfigured_bridge_returns_503(client, sample_camera_payload, monkeypatch, main_module):
    """If DEVICE_BRIDGE_TOKEN is empty, every protected request must 503."""
    monkeypatch.setattr(main_module, "DEVICE_BRIDGE_TOKEN", "")
    resp = client.post(
        "/cameras",
        json=sample_camera_payload,
        headers={"X-Bridge-Token": "anything"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_snapshot_unauthenticated(client):
    resp = client.post("/cameras/cam-1/snapshot")
    assert resp.status_code == 401


def test_connect_unauthenticated(client):
    resp = client.post(
        "/bridge/connect",
        json={"device_id": "cam-1", "sdp": "v=0\r\n", "type": "offer"},
    )
    assert resp.status_code == 401
