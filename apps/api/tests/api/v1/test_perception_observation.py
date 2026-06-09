"""Luna Phase 5.2 — governed perception transport (server) tests.

Covers `record_observation_artifact` + `perception_storage`: fail-closed gates
(capability flag, session ownership, device-token), quarantine write, a BYTE-FREE
`resource_referenced` event, and the no-byte-retrieval invariant (no GET route
returns observation bytes).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.chat import ChatSession
from app.models.device_registry import DeviceRegistry
from app.models.perception_artifact import PerceptionArtifact
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.user import User
from app.services import desktop_control_service as svc
from app.services import perception_storage

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222223")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
DEVICE_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
DEVICE_TOKEN = "device-token-test"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-redacted-bytes" * 4


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _quarantine_root(tmp_path, monkeypatch):
    # Never write to the real /var quarantine during tests.
    monkeypatch.setenv("OBSERVATION_QUARANTINE_ROOT", str(tmp_path / "observations"))


def _seed(db: Session, *, control_enabled: bool = True, owner=USER_ID):
    db.add_all([
        Tenant(id=TENANT_ID, name="Perception Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="p@example.test", hashed_password="x"),
        User(id=OTHER_USER_ID, tenant_id=TENANT_ID, email="o@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=owner, title="s"),
        DeviceRegistry(
            id=DEVICE_ID,
            tenant_id=TENANT_ID,
            device_id=f"{TENANT_ID}-desktop",
            device_name="Luna Desktop",
            device_type="desktop",
            status="online",
            device_token_hash=hashlib.sha256(DEVICE_TOKEN.encode()).hexdigest(),
            capabilities=["can_observe"],
            config={"shell_id": SHELL_ID},
        ),
        TenantFeatures(tenant_id=TENANT_ID, desktop_control_enabled=control_enabled),
    ])
    db.commit()
    return db.query(User).filter(User.id == USER_ID).first()


def _record(db, user, **over):
    kwargs = dict(
        user=user,
        device_token=DEVICE_TOKEN,
        session_id=SESSION_ID,
        shell_id=SHELL_ID,
        data=PNG,
        source_window_bundle_id="com.apple.TextEdit",
    )
    kwargs.update(over)
    return svc.record_observation_artifact(db, **kwargs)


def test_stores_artifact_and_emits_byte_free_reference(db_session):
    user = _seed(db_session, control_enabled=True)
    captured = {}

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured["event_type"] = event_type
        captured["payload"] = payload
        return {"event_id": "evt-1", "seq_no": 7}

    with patch.object(svc, "publish_session_event", side_effect=fake_publish):
        artifact, session_event = _record(db_session, user)

    # row + bytes persisted
    row = db_session.query(PerceptionArtifact).filter(PerceptionArtifact.id == artifact.id).first()
    assert row is not None
    assert row.size_bytes == len(PNG)
    assert row.sha256 == hashlib.sha256(PNG).hexdigest()
    assert row.redaction_status == "not_planner_safe"  # P5.2 never claims redacted
    assert row.expires_at is not None and row.deleted_at is None
    import os
    assert os.path.exists(os.path.join(perception_storage.quarantine_root(), row.storage_path))

    # the SSE reference is BYTE-FREE
    assert captured["event_type"] == "resource_referenced"
    payload = captured["payload"]
    assert payload["resource_id"] == str(artifact.id)
    assert payload["resource_type"] == "screenshot"
    assert payload["hash"] == row.sha256
    assert payload["redaction_status"] == "not_planner_safe"
    blob = json.dumps(payload)
    assert "PNG" not in blob  # no raw bytes / base64 in the event
    import base64
    assert base64.b64encode(PNG).decode() not in blob


def test_denied_when_desktop_control_disabled(db_session):
    user = _seed(db_session, control_enabled=False)
    with patch.object(svc, "publish_session_event", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _record(db_session, user)
    assert exc.value.status_code == 403


def test_denied_when_session_not_owned(db_session):
    user = _seed(db_session, control_enabled=True, owner=OTHER_USER_ID)
    with pytest.raises(HTTPException) as exc:
        _record(db_session, user)
    assert exc.value.status_code == 403


def test_denied_on_bad_device_token(db_session):
    user = _seed(db_session, control_enabled=True)
    with pytest.raises(HTTPException) as exc:
        _record(db_session, user, device_token="wrong")
    assert exc.value.status_code == 401


def test_storage_rejects_empty_and_oversized():
    # Pure-logic: fail-closed BEFORE any db/file IO (db unused on the raise path).
    with pytest.raises(perception_storage.PerceptionStorageError):
        perception_storage.save_observation_artifact(
            None, tenant_id=TENANT_ID, session_id=SESSION_ID, shell_id=SHELL_ID,
            device_id=DEVICE_ID, data=b"",
        )
    with pytest.raises(perception_storage.PerceptionStorageError):
        perception_storage.save_observation_artifact(
            None, tenant_id=TENANT_ID, session_id=SESSION_ID, shell_id=SHELL_ID,
            device_id=DEVICE_ID, data=b"x" * 100, max_size_bytes=10,
        )


def test_relpath_is_tenant_session_scoped_and_traversal_free():
    rel = perception_storage.artifact_relpath(TENANT_ID, SESSION_ID, DEVICE_ID)
    assert rel == f"{TENANT_ID}/{SESSION_ID}/{DEVICE_ID}.png"
    assert ".." not in rel


def test_no_byte_retrieval_route_exists():
    # No-read by construction: there must be NO route that returns observation
    # bytes (no GET on the observations resource).
    from app.api.v1 import desktop_control
    for route in desktop_control.router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "observations" in path and path != "/internal/observations/request":
            assert methods == {"POST"}, f"unexpected method on {path}: {methods}"
            assert "GET" not in methods


def _find_repo_file(name: str) -> str | None:
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        cand = os.path.join(root, name)
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent
    return None


def test_observations_quarantine_volume_is_api_only():
    """No-leak invariant (Codex/Luna BLOCKER): the perception quarantine volume
    must be mounted on `api` and NEVER on any agent runtime (code-worker /
    orchestration-worker), else 'no-read by construction' is false. Test-enforced
    in CI (full checkout); skipped where docker-compose.yml is not present."""
    import yaml

    compose_path = _find_repo_file("docker-compose.yml")
    if compose_path is None:
        pytest.skip("docker-compose.yml not in this checkout")
    with open(compose_path) as fh:
        data = yaml.safe_load(fh)
    services = data.get("services", {})

    def mounts_observations(name: str) -> bool:
        for v in services.get(name, {}).get("volumes") or []:
            if isinstance(v, str) and v.split(":", 1)[0].strip() == "observations":
                return True
        return False

    assert mounts_observations("api"), "api must mount the observations quarantine"
    for agent in ("code-worker", "orchestration-worker"):
        assert not mounts_observations(agent), (
            f"{agent} must NOT mount the observations quarantine (no-read invariant)"
        )
