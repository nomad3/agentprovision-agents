"""Luna Phase 5.3a-2 — perception-redactor DRIVER tests.

Covers the sweep-integrated driver (`run_redactor_once`), the PERCEPTION_REDACTOR_ENABLED
flag gate (off ⇒ artifacts stay not_planner_safe with a display-safe reason), byte-free
status-transition events, and the lows that go live with the driver: TTL race, dangling
planner_safe after ambiguous failure, short-write handling, unknown region-kind
fail-closed, and max-attempts coverage. No native actuation; no real engine (stubbed).
"""
from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.base import Base
from app.db.session import SessionLocal, engine as db_engine
from app.models.chat import ChatSession
from app.models.perception_artifact import PerceptionArtifact
from app.models.tenant import Tenant
from app.models.user import User
from app.services import perception_redactor as pr
from app.services import perception_storage

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SESSION_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SHELL_ID = "desktop-44444444-4444-4444-4444-444444444444"
WORKER = "perception-redactor-test"

# A real secret shape the cli_orchestrator floor recognises.
SECRET = "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def _utc(min_offset=0):
    return datetime.now(timezone.utc) + timedelta(minutes=min_offset)


def _make_png(w=64, h=48) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


class StubEngine:
    """Returns ``regions`` on the first detect (raw), ``verify`` on the re-OCR pass."""

    def __init__(self, regions, verify=None):
        self._regions = regions
        self._verify = verify if verify is not None else []
        self._calls = 0

    def detect(self, image_bytes, *, width, height):
        self._calls += 1
        return list(self._regions if self._calls == 1 else self._verify)


class RaisingEngine:
    def detect(self, image_bytes, *, width, height):
        raise RuntimeError("engine boom")


@pytest.fixture(name="db_session")
def db_session_fixture():
    Base.metadata.create_all(bind=db_engine)
    db = SessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=db_engine)


@pytest.fixture(autouse=True)
def _quarantine_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSERVATION_QUARANTINE_ROOT", str(tmp_path / "obs"))


@pytest.fixture(autouse=True)
def _silence_session_events(monkeypatch):
    # The real publish_session_event allocates a Postgres-only seq via
    # pg_advisory_xact_lock(hashtext(...)) — unavailable on the SQLite test DB. The
    # driver's status events are verified independently (test_status_event_is_byte_free
    # passes its own capturing sink); here we no-op the default sink so the redaction
    # logic is tested hermetically, independent of the SSE/Postgres infra.
    monkeypatch.setattr(pr, "_default_publish", lambda *a, **k: None)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("PERCEPTION_REDACTOR_ENABLED", "true")


def _seed_base(db):
    if db.get(Tenant, TENANT_ID) is None:
        db.add_all([
            Tenant(id=TENANT_ID, name="Redactor Tenant"),
            User(id=USER_ID, tenant_id=TENANT_ID, email="r@example.test", hashed_password="x"),
            ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=USER_ID, title="s"),
        ])
        db.commit()


def _seed_artifact(
    db, *, status=pr.STATUS_NOT_PLANNER_SAFE, claimed_by=None, claimed_at=None,
    attempts=0, expires_min=15, png=None,
):
    _seed_base(db)
    artifact_id = uuid.uuid4()
    rel = perception_storage.artifact_relpath(TENANT_ID, SESSION_ID, artifact_id)
    root = perception_storage.quarantine_root()
    abspath = os.path.join(root, rel)
    os.makedirs(os.path.dirname(abspath), mode=0o700, exist_ok=True)
    png = png if png is not None else _make_png()
    with open(abspath, "wb") as fh:
        fh.write(png)
    art = PerceptionArtifact(
        id=artifact_id, tenant_id=TENANT_ID, session_id=SESSION_ID, shell_id=SHELL_ID,
        device_id=None, artifact_type="screenshot", storage_path=rel,
        sha256="0" * 64, size_bytes=len(png), redaction_status=status,
        redact_claimed_by=claimed_by, redact_claimed_at=claimed_at, redact_attempts=attempts,
        expires_at=_utc(expires_min),
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


def _raw_path(art):
    return os.path.join(
        perception_storage.quarantine_root(),
        perception_storage.artifact_relpath(art.tenant_id, art.session_id, art.id),
    )


def _redacted_path(art):
    return perception_storage.redacted_abspath(
        perception_storage.redacted_relpath(art.tenant_id, art.session_id, art.id)
    )


def _region(box=(5, 5, 30, 10), text="", kind="text", conf=0.95):
    return pr.DetectedRegion(box=box, text=text, kind=kind, confidence=conf)


# ── flag gate: OFF ⇒ no work, display-safe reason ────────────────────────────

def test_driver_disabled_does_nothing_and_reports_reason(db_session):
    # PERCEPTION_REDACTOR_ENABLED unset (default off)
    art = _seed_artifact(db_session)
    res = pr.run_redactor_once(db_session, StubEngine([]), worker_id=WORKER)
    assert res.enabled is False
    assert res.reason == "redactor_disabled"
    assert res.processed == 0
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert art.redacted_storage_path is None and art.raw_deleted_at is None
    assert os.path.exists(_raw_path(art))  # raw untouched
    assert pr.planner_safety_reason(art) == "redactor_disabled"


def test_driver_enabled_but_no_engine_is_dormant(db_session, enabled):
    art = _seed_artifact(db_session)
    res = pr.run_redactor_once(db_session, None, worker_id=WORKER)
    assert res.enabled is True and res.reason == "no_engine" and res.processed == 0
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE


# ── happy path: clean + secret ⇒ planner_safe, raw deleted ───────────────────

def test_driver_clean_image_becomes_planner_safe_with_raw_deleted(db_session, enabled):
    art = _seed_artifact(db_session)
    res = pr.run_redactor_once(db_session, StubEngine([]), worker_id=WORKER)
    assert res.processed == 1 and res.planner_safe == 1 and res.withheld == 0
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE
    # planner_safe REQUIRES raw deletion — raw gone, redacted present, never coexist.
    assert art.raw_deleted_at is not None
    assert art.redacted_storage_path is not None
    assert not os.path.exists(_raw_path(art))
    assert os.path.exists(_redacted_path(art))
    assert pr.planner_safety_reason(art) == "planner_safe"


def test_driver_redacts_localized_secret(db_session, enabled):
    art = _seed_artifact(db_session)
    engine = StubEngine([_region(text=SECRET)], verify=[])  # secret gone after redaction
    res = pr.run_redactor_once(db_session, engine, worker_id=WORKER)
    assert res.planner_safe == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE
    assert (art.redaction_meta or {}).get("redact_count") == 1
    # the SECRET must be absent from the redacted BYTES
    with open(_redacted_path(art), "rb") as fh:
        assert SECRET.encode() not in fh.read()


def test_driver_withholds_and_keeps_raw_when_secret_survives(db_session, enabled):
    art = _seed_artifact(db_session)
    # verify pass still finds the secret ⇒ withhold; raw must NOT be deleted.
    engine = StubEngine([_region(text=SECRET)], verify=[_region(text=SECRET)])
    res = pr.run_redactor_once(db_session, engine, worker_id=WORKER)
    assert res.planner_safe == 0 and res.withheld == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert art.raw_deleted_at is None and art.redacted_storage_path is None
    assert os.path.exists(_raw_path(art))  # raw kept for TTL reaping
    assert "secret_survived_redaction" in (art.redaction_meta or {}).get("reasons", [])
    assert pr.planner_safety_reason(art) == "withheld"


# ── byte-free status events ──────────────────────────────────────────────────

def test_status_event_is_byte_free(db_session, enabled):
    _seed_artifact(db_session)
    captured = []

    def fake_publish(session_id, event_type, payload, *, tenant_id):
        captured.append((session_id, event_type, payload, tenant_id))

    pr.run_redactor_once(db_session, StubEngine([_region(text=SECRET)]),
                         worker_id=WORKER, publish=fake_publish)
    assert len(captured) == 1
    sid, etype, payload, tid = captured[0]
    assert etype == "perception_redaction"
    assert sid == str(SESSION_ID) and tid == str(TENANT_ID)
    assert set(payload) <= {"resource_type", "resource_id", "redaction_status", "reason", "redact_count"}
    blob = json.dumps(payload)
    assert SECRET not in blob  # no raw OCR text
    # no filesystem path / quarantine bytes leak
    assert "/" not in payload["reason"] and ".png" not in blob


# ── retries + max-attempts coverage (Low 5) ──────────────────────────────────

def test_failing_engine_retries_then_stops_at_max_attempts(db_session, enabled, monkeypatch):
    monkeypatch.setenv("PERCEPTION_REDACTOR_MAX_ATTEMPTS", "2")
    art = _seed_artifact(db_session)
    # pass 1 + 2 both fail (engine raises) ⇒ withheld, attempts climb to the cap.
    pr.run_redactor_once(db_session, RaisingEngine(), worker_id=WORKER, batch_size=1)
    pr.run_redactor_once(db_session, RaisingEngine(), worker_id=WORKER, batch_size=1)
    db_session.refresh(art)
    assert art.redact_attempts == 2 and art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    # exhausted ⇒ claim_next no longer picks it up.
    assert pr.claim_next_for_redaction(db_session, worker_id=WORKER, max_attempts=2) is None


def test_recover_exhausted_finalizes_stuck_redacting(db_session, enabled, monkeypatch):
    monkeypatch.setenv("PERCEPTION_REDACTOR_MAX_ATTEMPTS", "3")
    # a row stuck in `redacting` (crashed worker on its final attempt), lease stale.
    art = _seed_artifact(
        db_session, status=pr.STATUS_REDACTING, claimed_by="dead-worker",
        claimed_at=_utc(-30), attempts=3,
    )
    recovered = pr.recover_exhausted_redacting(db_session, max_attempts=3, lease_timeout_seconds=120)
    assert recovered == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    meta = art.redaction_meta or {}
    assert meta.get("terminal") is True and "max_attempts_exhausted" in meta.get("reasons", [])
    assert art.redact_claimed_by is None


def test_recover_skips_fresh_lease(db_session, enabled):
    art = _seed_artifact(
        db_session, status=pr.STATUS_REDACTING, claimed_by="live-worker",
        claimed_at=_utc(0), attempts=3,
    )
    assert pr.recover_exhausted_redacting(db_session, max_attempts=3, lease_timeout_seconds=120) == 0
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_REDACTING  # in-flight, left alone


# ── expired raw handling + TTL race (Low 1) ──────────────────────────────────

def test_expired_artifact_not_claimed(db_session, enabled):
    art = _seed_artifact(db_session, expires_min=-5)  # already expired
    assert pr.claim_next_for_redaction(db_session, worker_id=WORKER) is None
    res = pr.run_redactor_once(db_session, StubEngine([]), worker_id=WORKER)
    assert res.processed == 0
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE  # untouched, TTL reaps raw


def test_cleanup_skips_in_flight_redacting_but_reaps_stale(db_session):
    now = datetime.now(timezone.utc)
    # all three expired; only the actively-leased redacting one must be spared.
    fresh = _seed_artifact(db_session, status=pr.STATUS_REDACTING,
                           claimed_by="w", claimed_at=now, attempts=1, expires_min=-1)
    stale = _seed_artifact(db_session, status=pr.STATUS_REDACTING, claimed_by="w",
                           claimed_at=now - timedelta(seconds=300), attempts=1, expires_min=-1)
    plain = _seed_artifact(db_session, expires_min=-1)
    ids = {a.id for a in perception_storage.expired_artifacts(db_session, now=now)}
    assert fresh.id not in ids  # TTL-race guard: in-flight redaction spared
    assert stale.id in ids and plain.id in ids


# ── unknown region-kind fail-closed (Low 4) ──────────────────────────────────

def test_unknown_region_kind_withholds(db_session, enabled):
    art = _seed_artifact(db_session)
    engine = StubEngine([_region(box=(0, 0, 20, 20), text="", kind="signature")])
    res = pr.run_redactor_once(db_session, engine, worker_id=WORKER)
    assert res.withheld == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert "unknown_region_kind:signature" in (art.redaction_meta or {}).get("reasons", [])


def test_classify_unknown_kind_unit():
    out = pr._classify_regions([_region(kind="logo", text="")])
    assert out.withhold and any(r.startswith("unknown_region_kind:") for r in out.reasons)


# ── short-write handling (Low 3) ─────────────────────────────────────────────

def test_short_write_loop_completes(db_session, enabled, monkeypatch):
    art = _seed_artifact(db_session)
    real_write = os.write

    def chunked_write(fd, data):  # os.write may write fewer bytes — emulate it
        return real_write(fd, bytes(data[:8]))

    monkeypatch.setattr(os, "write", chunked_write)
    res = pr.run_redactor_once(db_session, StubEngine([]), worker_id=WORKER)
    monkeypatch.setattr(os, "write", real_write)
    assert res.planner_safe == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE
    # the redacted file is complete (size matches the row's recorded size)
    assert os.path.getsize(_redacted_path(art)) == art.size_bytes


def test_zero_write_fails_closed(db_session, enabled, monkeypatch):
    art = _seed_artifact(db_session)

    def zero_write(fd, data):
        return 0  # no progress ⇒ short-write guard must raise

    monkeypatch.setattr(os, "write", zero_write)
    res = pr.run_redactor_once(db_session, StubEngine([]), worker_id=WORKER)
    # NB: don't monkeypatch.undo() here — it would also revert the autouse
    # OBSERVATION_QUARANTINE_ROOT setenv (shared monkeypatch). os.write is restored
    # at teardown; the remaining assertions don't write via os.write.
    assert res.planner_safe == 0 and res.withheld == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert art.raw_deleted_at is None and os.path.exists(_raw_path(art))
    assert not os.path.exists(_redacted_path(art))  # no truncated file published


# ── dangling planner_safe after ambiguous failure (Low 2 regression) ─────────

def test_finish_withheld_leaves_committed_planner_safe(db_session, enabled):
    art = _seed_artifact(db_session)
    art.redaction_status = pr.STATUS_PLANNER_SAFE
    art.raw_deleted_at = _utc(0)
    art.redacted_storage_path = "x.redacted.png"
    db_session.add(art)
    db_session.commit()
    outcome = pr._finish_withheld(db_session, art.id, None, reason_override="ambiguous_post_commit")
    assert outcome.status == "planner_safe"
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE  # NOT reverted
    assert art.raw_deleted_at is not None
