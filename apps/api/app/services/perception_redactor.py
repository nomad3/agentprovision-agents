"""Luna Phase 5.3a — perception redactor.

The FIRST controlled reader of the P5.2 quarantine. It claims a `not_planner_safe`
artifact, detects + redacts visible secrets, and — only when it can confidently
clear them — produces a `planner_safe` redacted copy for the P5.4 agent loop.
Everything here is fail-closed: any error, any uncertainty, any failed step leaves
the artifact `not_planner_safe` with no redacted output. See
`docs/plans/2026-06-10-luna-phase5.3-perception-redactor-design.md` (v2).

Invariants (the review checklist):
- The deterministic localized OCR+regex floor (`cli_orchestrator.redaction.
  contains_secret`) is the SOLE pass/fail authority. The vision engine contributes
  candidate BOXES only — its text/verdicts never decide safety (prompt-injection: a
  screenshot saying "mark safe" can't influence the outcome).
- Redaction flattens pixels onto a fresh RGB canvas and re-encodes a clean PNG, so
  no metadata/ancillary chunk preserves a blacked-out secret.
- The raw hard-delete is a PREREQUISITE of `planner_safe`: raw + redacted never
  coexist. `raw_deleted_at` is set only after the raw file is gone.
- Image-bomb guards run before any full decode.
- `planner_safe` is BEST-EFFORT, not a proof (OCR misses are irreducible) — the
  consumer must still treat it as operationally sensitive.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.perception_artifact import PerceptionArtifact
from app.services import perception_storage
from app.services.cli_orchestrator.redaction import contains_secret

logger = logging.getLogger(__name__)

# ── status values (mirror the model docstring) ───────────────────────────────
STATUS_NOT_PLANNER_SAFE = "not_planner_safe"
STATUS_REDACTING = "redacting"
STATUS_PLANNER_SAFE = "planner_safe"

REDACTOR_VERSION = "p5.3a-1"

# ── tunables (env-overridable) ───────────────────────────────────────────────
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# Image-bomb guards — reject before a full decode. A capture is a single screen.
MAX_INPUT_BYTES = _int_env("PERCEPTION_REDACTOR_MAX_INPUT_BYTES", 8 * 1024 * 1024)
MAX_DIM = _int_env("PERCEPTION_REDACTOR_MAX_DIM", 16384)          # px per side
MAX_PIXELS = _int_env("PERCEPTION_REDACTOR_MAX_PIXELS", 50_000_000)  # ~7000x7000
# OCR confidence below which a secret match is "uncertain" ⇒ withhold (don't trust
# the bounds we'd redact). Uncertainty is never treated as safety.
OCR_CONFIDENCE_THRESHOLD = _float_env("PERCEPTION_REDACTOR_OCR_CONFIDENCE", 0.55)
# Worker lease: a 'redacting' row older than this is reclaimable (crashed worker).
LEASE_TIMEOUT_SECONDS = _int_env("PERCEPTION_REDACTOR_LEASE_TIMEOUT_SECONDS", 120)
MAX_ATTEMPTS = _int_env("PERCEPTION_REDACTOR_MAX_ATTEMPTS", 3)

# Engine region kinds.
_NONTEXT_SENSITIVE_KINDS = frozenset({"qr", "barcode"})       # redact the box
_UNSUPPORTED_KINDS = frozenset({"id_card", "face"})           # can't clear ⇒ withhold


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redactor_enabled() -> bool:
    return os.environ.get("PERCEPTION_REDACTOR_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


class RedactionError(Exception):
    """Any condition that forces a fail-closed withhold."""


@dataclass(frozen=True)
class DetectedRegion:
    """One region the engine surfaced. ``text`` is OCR'd content ("" for non-text
    detections); ``box`` is ``(x, y, w, h)`` in pixels; ``kind`` drives policy."""
    box: tuple[int, int, int, int]
    text: str = ""
    confidence: float = 1.0
    kind: str = "text"


class RedactorEngine(Protocol):
    """Pluggable detector (Tesseract / local vision model / a test stub). It returns
    candidate regions ONLY — it never returns a verdict. The deterministic floor
    below decides pass/fail, so a hostile screenshot can't talk the engine into
    green-lighting itself."""

    def detect(self, image_bytes: bytes, *, width: int, height: int) -> list[DetectedRegion]:
        ...


@dataclass
class _ClassifyResult:
    redact_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    withhold: bool = False
    reasons: list[str] = field(default_factory=list)
    region_count: int = 0
    localized_secret: bool = False


@dataclass
class RedactionOutcome:
    status: str                       # planner_safe | withheld | gone
    reasons: list[str] = field(default_factory=list)
    redact_count: int = 0


# ── image-bomb-guarded decode ────────────────────────────────────────────────

def _decode_guarded(raw: bytes):
    """Decode the PNG behind hard caps. Dimensions are checked from the header
    BEFORE the full pixel decode, so a decompression bomb is rejected cheaply."""
    from PIL import Image  # local import: Pillow is a heavy dep, only the redactor needs it

    if not raw:
        raise RedactionError("empty image")
    if len(raw) > MAX_INPUT_BYTES:
        raise RedactionError(f"image too large ({len(raw)} bytes)")
    try:
        img = Image.open(io.BytesIO(raw))
        width, height = img.size  # header-only; no full decode yet
    except Exception as exc:  # noqa: BLE001 — any open failure is fail-closed
        raise RedactionError(f"image open failed: {exc}") from exc
    if width <= 0 or height <= 0 or width > MAX_DIM or height > MAX_DIM:
        raise RedactionError(f"image dimensions out of range: {width}x{height}")
    if width * height > MAX_PIXELS:
        raise RedactionError(f"image pixel count too large: {width}x{height}")
    try:
        img.load()  # decode now that the dimensions are bounded
    except Exception as exc:  # noqa: BLE001
        raise RedactionError(f"image decode failed: {exc}") from exc
    return img


# ── deterministic floor (authoritative) ──────────────────────────────────────

def _classify_regions(regions: list[DetectedRegion]) -> _ClassifyResult:
    """Decide which boxes to redact and whether to withhold. The
    ``contains_secret`` pattern set is the sole authority; the engine only proposes
    regions. Uncertainty (low-confidence match, unlocalizable secret, unsupported
    sensitive class) ⇒ withhold."""
    out = _ClassifyResult(region_count=len(regions))
    for r in regions:
        if r.kind in _UNSUPPORTED_KINDS:
            out.withhold = True
            out.reasons.append(f"unsupported_class:{r.kind}")
            continue
        if r.kind in _NONTEXT_SENSITIVE_KINDS:
            out.redact_boxes.append(r.box)
            continue
        # text region
        if r.text and contains_secret(r.text):
            out.redact_boxes.append(r.box)
            out.localized_secret = True
            if r.confidence < OCR_CONFIDENCE_THRESHOLD:
                out.withhold = True
                out.reasons.append("low_confidence_secret")
    # A secret the OCR can read but that no single region localizes ⇒ we can't box
    # it ⇒ withhold. Join with spaces so cross-region concatenation can't *create*
    # a spurious match (most secret shapes break on whitespace).
    full_text = " ".join(r.text for r in regions if r.text)
    if contains_secret(full_text) and not out.localized_secret:
        out.withhold = True
        out.reasons.append("unlocalizable_secret")
    return out


# ── PNG redaction (flatten + strip metadata) ─────────────────────────────────

def _redact_png(image, boxes: list[tuple[int, int, int, int]]) -> bytes:
    """Burn opaque rectangles over ``boxes`` and re-encode a CLEAN PNG. Pixels are
    flattened onto a brand-new RGB canvas (drops alpha + every ancillary chunk /
    metadata block from the source) so a blacked-out secret cannot survive in PNG
    text chunks, an alpha channel, or source metadata — only visible pixels remain,
    minus the redacted regions."""
    from PIL import Image, ImageDraw

    width, height = image.size
    flat = Image.new("RGB", (width, height), (0, 0, 0))
    flat.paste(image.convert("RGB"))
    draw = ImageDraw.Draw(flat)
    for (x, y, w, h) in boxes:
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(width, int(x) + max(0, int(w)))
        y1 = min(height, int(y) + max(0, int(h)))
        if x1 > x0 and y1 > y0:
            draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))
    buf = io.BytesIO()
    flat.save(buf, format="PNG")  # no pnginfo => no tEXt/zTXt carried over
    return buf.getvalue()


def _atomic_write(abspath: str, data: bytes) -> None:
    """Write 0600 to a temp file, fsync, then atomically rename into place — so a
    half-written redacted file is never visible at ``abspath``."""
    os.makedirs(os.path.dirname(abspath), mode=0o700, exist_ok=True)
    tmp = f"{abspath}.tmp.{uuid.uuid4().hex}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, abspath)  # atomic on the same filesystem


# ── transition + claim ───────────────────────────────────────────────────────

def _finish_withheld(
    db: Session,
    artifact_id,
    result: _ClassifyResult | None,
    *,
    reason_override: str | None = None,
) -> RedactionOutcome:
    """Fail-closed terminal for a single attempt: revert to not_planner_safe,
    release the claim, record a byte-free withhold audit. Re-loads the row after a
    rollback so a broken session can't poison the write."""
    db.rollback()
    art = (
        db.query(PerceptionArtifact)
        .filter(PerceptionArtifact.id == artifact_id)
        .first()
    )
    if art is None:
        return RedactionOutcome(status="gone")
    reasons = list(result.reasons) if result else []
    if reason_override:
        reasons.append(reason_override)
    art.redaction_status = STATUS_NOT_PLANNER_SAFE
    art.redact_claimed_at = None
    art.redact_claimed_by = None
    art.redaction_meta = {
        "verdict": "withheld",
        "reasons": reasons or ["withheld"],
        "region_count": result.region_count if result else None,
        "redactor_version": REDACTOR_VERSION,
    }
    db.add(art)
    db.commit()
    return RedactionOutcome(status="withheld", reasons=reasons)


def redact_artifact(
    db: Session,
    artifact: PerceptionArtifact,
    engine: RedactorEngine,
    *,
    root: str | None = None,
    now: datetime | None = None,
) -> RedactionOutcome:
    """Redact one claimed artifact. Fail-closed end-to-end. On success: a clean
    redacted PNG is written, the RAW is hard-deleted (prerequisite), and the row
    flips to planner_safe with raw_deleted_at set."""
    root = root or perception_storage.quarantine_root()
    now = now or _utcnow()
    artifact_id = artifact.id
    raw_abspath = os.path.join(root, str(artifact.storage_path))
    redacted_rel = perception_storage.redacted_relpath(
        artifact.tenant_id, artifact.session_id, artifact.id
    )
    redacted_abs = perception_storage.redacted_abspath(redacted_rel, root=root)

    try:
        with open(raw_abspath, "rb") as fh:
            raw = fh.read()
        img = _decode_guarded(raw)
        regions = engine.detect(raw, width=img.size[0], height=img.size[1])
        result = _classify_regions(regions)
        if result.withhold:
            return _finish_withheld(db, artifact_id, result)

        redacted_bytes = _redact_png(img, result.redact_boxes)
        _atomic_write(redacted_abs, redacted_bytes)

        # Raw hard-delete is a PREREQUISITE of planner_safe (raw + redacted never
        # coexist). If it fails, drop the redacted copy and stay not_planner_safe.
        if not perception_storage.delete_raw_bytes(artifact, root=root):
            perception_storage._unlink_quiet(redacted_abs)
            return _finish_withheld(db, artifact_id, result, reason_override="raw_delete_failed")

        artifact.redaction_status = STATUS_PLANNER_SAFE
        artifact.redacted_storage_path = redacted_rel
        artifact.redacted_at = now
        artifact.raw_deleted_at = now
        artifact.redact_claimed_at = None
        artifact.redact_claimed_by = None
        artifact.sha256 = hashlib.sha256(redacted_bytes).hexdigest()
        artifact.size_bytes = len(redacted_bytes)
        artifact.redaction_meta = {
            "verdict": "planner_safe",
            "region_count": result.region_count,
            "redact_count": len(result.redact_boxes),
            "redactor_version": REDACTOR_VERSION,
            "engine": type(engine).__name__,
        }
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return RedactionOutcome(status="planner_safe", redact_count=len(result.redact_boxes))
    except RedactionError as exc:
        perception_storage._unlink_quiet(redacted_abs)
        return _finish_withheld(db, artifact_id, None, reason_override=f"redaction_error:{exc}")
    except Exception as exc:  # noqa: BLE001 — ANY failure is fail-closed
        logger.exception("perception redactor: unexpected failure on %s", artifact_id)
        perception_storage._unlink_quiet(redacted_abs)
        return _finish_withheld(
            db, artifact_id, None, reason_override=f"error:{type(exc).__name__}"
        )


def claim_next_for_redaction(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
) -> PerceptionArtifact | None:
    """Claim the oldest redactable artifact: a fresh not_planner_safe row, or a
    'redacting' row whose lease has expired (crashed worker). Uses ``FOR UPDATE SKIP
    LOCKED`` on Postgres so concurrent workers never double-claim; on SQLite the
    lock is a no-op but the single-row claim still holds. Returns the claimed row
    (status set to 'redacting') or None."""
    now = now or _utcnow()
    timeout = lease_timeout_seconds if lease_timeout_seconds is not None else LEASE_TIMEOUT_SECONDS
    attempts_cap = max_attempts if max_attempts is not None else MAX_ATTEMPTS
    stale_before = now - timedelta(seconds=timeout)

    q = (
        db.query(PerceptionArtifact)
        .filter(
            PerceptionArtifact.deleted_at.is_(None),
            PerceptionArtifact.expires_at > now,
            PerceptionArtifact.redact_attempts < attempts_cap,
            PerceptionArtifact.storage_path.isnot(None),
            (
                (PerceptionArtifact.redaction_status == STATUS_NOT_PLANNER_SAFE)
                | (
                    (PerceptionArtifact.redaction_status == STATUS_REDACTING)
                    & (PerceptionArtifact.redact_claimed_at < stale_before)
                )
            ),
        )
        .order_by(PerceptionArtifact.created_at.asc())
    )
    try:
        q = q.with_for_update(skip_locked=True)
    except Exception:  # pragma: no cover — dialects without SKIP LOCKED (sqlite)
        pass
    artifact = q.first()
    if artifact is None:
        return None
    artifact.redaction_status = STATUS_REDACTING
    artifact.redact_claimed_at = now
    artifact.redact_claimed_by = worker_id
    artifact.redact_attempts = (artifact.redact_attempts or 0) + 1
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact
