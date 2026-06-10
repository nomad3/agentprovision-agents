"""Luna Phase 5.3a — perception redactor tests.

Covers the security-critical core: the deterministic floor (authoritative), the
metadata-stripping redaction (secret absent from BYTES), image-bomb guards, the
fail-closed atomic transition (raw hard-delete is a prerequisite of planner_safe),
and the worker lease/claim.
"""
from __future__ import annotations

import io
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

# A real secret shape the cli_orchestrator floor recognises (sk- api key, 20+ chars).
SECRET = "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
CLEAN = "Submit"


def _utc(dt_offset_min=0):
    return datetime.now(timezone.utc) + timedelta(minutes=dt_offset_min)


def _make_png(w=64, h=48, *, text_meta=None) -> bytes:
    from PIL import Image, PngImagePlugin

    img = Image.new("RGB", (w, h), (255, 255, 255))
    buf = io.BytesIO()
    if text_meta:
        info = PngImagePlugin.PngInfo()
        for k, v in text_meta.items():
            info.add_text(k, v)
        img.save(buf, format="PNG", pnginfo=info)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


class StubEngine:
    def __init__(self, regions):
        self._regions = regions

    def detect(self, image_bytes, *, width, height):
        return list(self._regions)


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


def _seed_artifact(db, *, root):
    db.add_all([
        Tenant(id=TENANT_ID, name="Redactor Tenant"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="r@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=USER_ID, title="s"),
    ])
    artifact_id = uuid.uuid4()
    rel = perception_storage.artifact_relpath(TENANT_ID, SESSION_ID, artifact_id)
    abspath = os.path.join(root, rel)
    os.makedirs(os.path.dirname(abspath), mode=0o700, exist_ok=True)
    png = _make_png()
    with open(abspath, "wb") as fh:
        fh.write(png)
    art = PerceptionArtifact(
        id=artifact_id, tenant_id=TENANT_ID, session_id=SESSION_ID, shell_id=SHELL_ID,
        device_id=None, artifact_type="screenshot", storage_path=rel,
        sha256="0" * 64, size_bytes=len(png), redaction_status=pr.STATUS_NOT_PLANNER_SAFE,
        expires_at=_utc(15), created_at=_utc(0),
    )
    db.add(art)
    db.commit()
    return art, abspath


# ── deterministic floor (authoritative) ──────────────────────────────────────


def test_floor_redacts_secret_region_and_passes():
    res = pr._classify_regions([
        pr.DetectedRegion(box=(10, 10, 50, 12), text=SECRET, confidence=0.9),
        pr.DetectedRegion(box=(10, 30, 50, 12), text=CLEAN, confidence=0.9),
    ])
    assert not res.withhold
    assert res.redact_boxes == [(10, 10, 50, 12)]  # only the secret box
    assert res.localized_secret


def test_floor_withholds_low_confidence_secret():
    res = pr._classify_regions([
        pr.DetectedRegion(box=(0, 0, 10, 10), text=SECRET, confidence=0.2),  # below threshold
    ])
    assert res.withhold
    assert "low_confidence_secret" in res.reasons


def test_floor_withholds_unlocalizable_secret():
    # The secret only matches when regions are JOINED ("cookie:" + a value), never
    # within one box — so we can't box it ⇒ withhold. ("cookie:" alone needs content
    # after the colon to match; the value alone matches nothing.)
    res = pr._classify_regions([
        pr.DetectedRegion(box=(0, 0, 10, 10), text="cookie:", confidence=0.9),
        pr.DetectedRegion(box=(0, 20, 10, 10), text="abcdef-session-token-value", confidence=0.9),
    ])
    assert res.withhold
    assert "unlocalizable_secret" in res.reasons
    assert not res.localized_secret


def test_floor_withholds_unsupported_class():
    res = pr._classify_regions([pr.DetectedRegion(box=(0, 0, 10, 10), text="", kind="id_card")])
    assert res.withhold
    assert any("unsupported_class" in r for r in res.reasons)


def test_floor_redacts_qr_box():
    res = pr._classify_regions([pr.DetectedRegion(box=(5, 5, 20, 20), text="", kind="qr")])
    assert not res.withhold
    assert res.redact_boxes == [(5, 5, 20, 20)]


def test_floor_clean_image_passes_with_no_redaction():
    res = pr._classify_regions([
        pr.DetectedRegion(box=(0, 0, 10, 10), text=CLEAN, confidence=0.9),
    ])
    assert not res.withhold and res.redact_boxes == []


# ── redaction strips metadata (secret absent from BYTES) ──────────────────────


def test_redact_png_strips_source_metadata_secret():
    from PIL import Image

    raw = _make_png(64, 48, text_meta={"Comment": SECRET})
    assert SECRET.encode() in raw  # the secret IS in the source PNG metadata
    img = Image.open(io.BytesIO(raw))
    img.load()
    redacted = pr._redact_png(img, [(0, 0, 10, 10)])
    # the fresh re-encode drops all ancillary chunks → secret gone from the bytes
    assert SECRET.encode() not in redacted
    # and it is a valid PNG
    assert redacted.startswith(b"\x89PNG\r\n\x1a\n")


# ── image-bomb guards ─────────────────────────────────────────────────────────


def test_decode_guarded_rejects_oversized_bytes():
    with pytest.raises(pr.RedactionError):
        pr._decode_guarded(b"x" * (pr.MAX_INPUT_BYTES + 1))


def test_decode_guarded_rejects_huge_dimensions(monkeypatch):
    monkeypatch.setattr(pr, "MAX_DIM", 32)
    big = _make_png(100, 100)  # 100 > MAX_DIM=32
    with pytest.raises(pr.RedactionError):
        pr._decode_guarded(big)


def test_decode_guarded_rejects_non_image():
    with pytest.raises(pr.RedactionError):
        pr._decode_guarded(b"not a png at all")


def test_decode_guarded_accepts_valid_png():
    img = pr._decode_guarded(_make_png(40, 30))
    assert img.size == (40, 30)


# ── redact_artifact: fail-closed atomic transition ───────────────────────────


def test_redact_artifact_clean_image_becomes_planner_safe(db_session):
    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    out = pr.redact_artifact(
        db_session, art, StubEngine([pr.DetectedRegion(box=(0, 0, 5, 5), text=CLEAN)]), root=root
    )
    assert out.status == "planner_safe"
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE
    assert art.redacted_storage_path and art.redacted_at and art.raw_deleted_at
    # raw is GONE (hard-delete prerequisite), redacted EXISTS
    assert not os.path.exists(raw_abs)
    assert os.path.exists(os.path.join(root, art.redacted_storage_path))


def test_redact_artifact_redacts_secret_region(db_session):
    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    out = pr.redact_artifact(
        db_session, art, StubEngine([pr.DetectedRegion(box=(0, 0, 20, 12), text=SECRET, confidence=0.9)]), root=root
    )
    assert out.status == "planner_safe" and out.redact_count == 1
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_PLANNER_SAFE
    assert not os.path.exists(raw_abs)


def test_redact_artifact_withholds_on_unsupported_class(db_session):
    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    out = pr.redact_artifact(
        db_session, art, StubEngine([pr.DetectedRegion(box=(0, 0, 5, 5), kind="id_card")]), root=root
    )
    assert out.status == "withheld"
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert art.redacted_storage_path is None and art.raw_deleted_at is None
    assert os.path.exists(raw_abs)  # raw NOT deleted on withhold
    assert not os.path.exists(os.path.join(root, perception_storage.redacted_relpath(TENANT_ID, SESSION_ID, art.id)))


def test_redact_artifact_fail_closed_on_engine_error(db_session):
    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    out = pr.redact_artifact(db_session, art, RaisingEngine(), root=root)
    assert out.status == "withheld"
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert os.path.exists(raw_abs)  # raw preserved on failure


def test_redact_artifact_raw_delete_failure_withholds_and_cleans(db_session, monkeypatch):
    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    monkeypatch.setattr(perception_storage, "delete_raw_bytes", lambda *a, **k: False)
    out = pr.redact_artifact(
        db_session, art, StubEngine([pr.DetectedRegion(box=(0, 0, 5, 5), text=CLEAN)]), root=root
    )
    assert out.status == "withheld"
    db_session.refresh(art)
    assert art.redaction_status == pr.STATUS_NOT_PLANNER_SAFE
    assert art.raw_deleted_at is None
    # the redacted copy we wrote was cleaned up (no orphan), raw still present
    assert not os.path.exists(os.path.join(root, perception_storage.redacted_relpath(TENANT_ID, SESSION_ID, art.id)))
    assert os.path.exists(raw_abs)


# ── claim / lease ─────────────────────────────────────────────────────────────


def test_claim_picks_up_not_planner_safe(db_session):
    root = perception_storage.quarantine_root()
    art, _ = _seed_artifact(db_session, root=root)
    claimed = pr.claim_next_for_redaction(db_session, worker_id="w1")
    assert claimed is not None and claimed.id == art.id
    assert claimed.redaction_status == pr.STATUS_REDACTING
    assert claimed.redact_claimed_by == "w1" and claimed.redact_attempts == 1


def test_claim_skips_expired_and_max_attempts(db_session):
    root = perception_storage.quarantine_root()
    art, _ = _seed_artifact(db_session, root=root)
    art.expires_at = _utc(-1)  # already expired
    db_session.add(art)
    db_session.commit()
    assert pr.claim_next_for_redaction(db_session, worker_id="w1") is None


def test_claim_reclaims_stale_redacting(db_session):
    root = perception_storage.quarantine_root()
    art, _ = _seed_artifact(db_session, root=root)
    art.redaction_status = pr.STATUS_REDACTING
    art.redact_claimed_at = _utc(-10)  # lease long expired
    art.redact_claimed_by = "dead-worker"
    db_session.add(art)
    db_session.commit()
    claimed = pr.claim_next_for_redaction(db_session, worker_id="w2", lease_timeout_seconds=120)
    assert claimed is not None and claimed.redact_claimed_by == "w2"


def test_claim_returns_none_when_nothing_to_do(db_session):
    # no artifacts seeded at all
    db_session.add_all([
        Tenant(id=TENANT_ID, name="t"),
        User(id=USER_ID, tenant_id=TENANT_ID, email="r@example.test", hashed_password="x"),
        ChatSession(id=SESSION_ID, tenant_id=TENANT_ID, owner_user_id=USER_ID, title="s"),
    ])
    db_session.commit()
    assert pr.claim_next_for_redaction(db_session, worker_id="w1") is None


# ── cleanup reaps the redacted copy too ──────────────────────────────────────


def test_cleanup_hard_delete_reaps_redacted_copy(db_session):
    from app.services import perception_cleanup

    root = perception_storage.quarantine_root()
    art, raw_abs = _seed_artifact(db_session, root=root)
    # redact it (raw gone, redacted written, planner_safe)
    pr.redact_artifact(db_session, art, StubEngine([pr.DetectedRegion(box=(0, 0, 5, 5), text=CLEAN)]), root=root)
    db_session.refresh(art)
    redacted_abs = os.path.join(root, art.redacted_storage_path)
    assert os.path.exists(redacted_abs)
    # expire + sweep
    art.expires_at = _utc(-1)
    db_session.add(art)
    db_session.commit()
    from unittest.mock import patch
    with patch.object(perception_cleanup, "publish_session_event", return_value=None):
        deleted = perception_cleanup.run_cleanup_once(db_session)
    assert deleted == 1
    assert not os.path.exists(redacted_abs)  # redacted bytes reaped
