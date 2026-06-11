"""Luna Phase 5.3a — perception redactor.

The FIRST controlled reader of the P5.2 quarantine. It claims a `not_planner_safe`
artifact, detects + redacts visible secrets, and — only when it can confidently
clear them — produces a `planner_safe` redacted copy for the P5.4 agent loop.
Everything here is fail-closed: any error, any uncertainty, any failed step leaves
the artifact `not_planner_safe` with no redacted output. See
`docs/plans/2026-06-10-luna-phase5.3-perception-redactor-design.md` (v2).

Invariants (the review checklist):
- The deterministic floor (`_floor_detects_secret`, built on the shared
  `cli_orchestrator.redaction` patterns + env-assignment / PEM / cloud-key shapes)
  is the SOLE pass/fail authority. The pluggable engine contributes candidate BOXES
  only — its text/verdicts never decide safety (a screenshot saying "mark safe"
  can't influence the outcome).
- After redaction, a **second detection pass re-runs on the REDACTED output**; if a
  secret still surfaces (a mis-aligned/under-sized box, a partial cover), the
  artifact is withheld. This is what makes "candidate boxes only" safe in practice
  even when the engine's geometry is wrong.
- Inputs are alpha-flattened over an opaque background BEFORE detection + redaction,
  so a secret hidden under transparent pixels can never be revealed by the RGB
  conversion. Multi-frame (APNG) inputs are withheld.
- Redaction flattens pixels onto a fresh RGB canvas and re-encodes a clean PNG, so
  no metadata/ancillary chunk preserves a blacked-out secret.
- The raw hard-delete is a PREREQUISITE of `planner_safe`: raw + redacted never
  coexist. `raw_deleted_at` is set only after the raw file is gone.
- The worker is fenced: `redact_artifact` re-checks it still owns the claim (status
  `redacting` + matching `redact_claimed_by`) before the raw-delete + commit, so a
  reclaimed stale worker can never finish another worker's artifact.
- `planner_safe` is BEST-EFFORT, not a proof (a secret the OCR consistently fails to
  read is irreducible) — the consumer must still treat it as operationally sensitive.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.perception_artifact import PerceptionArtifact
from app.services import perception_storage
from app.services.cli_orchestrator.redaction import SENSITIVE_ENV_KEYS, contains_secret

logger = logging.getLogger(__name__)

STATUS_NOT_PLANNER_SAFE = "not_planner_safe"
STATUS_REDACTING = "redacting"
STATUS_PLANNER_SAFE = "planner_safe"

REDACTOR_VERSION = "p5.3a-1"


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


MAX_INPUT_BYTES = _int_env("PERCEPTION_REDACTOR_MAX_INPUT_BYTES", 8 * 1024 * 1024)
MAX_DIM = _int_env("PERCEPTION_REDACTOR_MAX_DIM", 16384)
MAX_PIXELS = _int_env("PERCEPTION_REDACTOR_MAX_PIXELS", 50_000_000)
OCR_CONFIDENCE_THRESHOLD = _float_env("PERCEPTION_REDACTOR_OCR_CONFIDENCE", 0.55)
LEASE_TIMEOUT_SECONDS = _int_env("PERCEPTION_REDACTOR_LEASE_TIMEOUT_SECONDS", 120)
MAX_ATTEMPTS = _int_env("PERCEPTION_REDACTOR_MAX_ATTEMPTS", 3)
# A secret region whose box is smaller than this many px on either side is treated
# as un-coverable (mis-detected geometry) ⇒ withhold rather than emit a tiny mark.
MIN_SECRET_BOX_PX = _int_env("PERCEPTION_REDACTOR_MIN_SECRET_BOX_PX", 4)

_NONTEXT_SENSITIVE_KINDS = frozenset({"qr", "barcode"})
_UNSUPPORTED_KINDS = frozenset({"id_card", "face"})
# The only region kinds whose safety we can decide via the deterministic text floor.
# Any OTHER engine-proposed kind is fail-closed (withheld) so a new/unknown region
# type can never be silently treated as safe — adding a kind here is a deliberate act.
_TEXT_KINDS = frozenset({"text"})

# Perception-specific secret shapes that the CLI-output `contains_secret` rules do
# NOT cover (kept OUT of the shared `_RULES` so CLI-log redaction behaviour is
# unchanged). Two env-assignment detectors: the exact SENSITIVE_ENV_KEYS names AND a
# GENERIC `<NAME-ending-in-a-secret-word>=value` shape (catches AWS_SECRET_ACCESS_KEY,
# any *_SECRET / *_TOKEN / *_PASSWORD / *_API_KEY, etc.). Plus PEM private-key headers,
# AWS/Google/Slack cloud-key shapes.
_ENV_ASSIGN_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(k) for k in sorted(SENSITIVE_ENV_KEYS)) + r")\s*[:=]\s*\S",
)
_GENERIC_ASSIGN_RE = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|"
    r"SECRET[_-]?KEY|AUTH[_-]?TOKEN|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|"
    r"PRIVATE[_-]?KEY|CREDENTIAL|CLIENT[_-]?SECRET)[A-Z0-9_]*\s*[:=]\s*\S",
)
_PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_AWS_AKIA_RE = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_GOOGLE_API_RE = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
_SLACK_RE = re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")
_EXTRA_SECRET_RES = (
    _ENV_ASSIGN_RE, _GENERIC_ASSIGN_RE, _PEM_RE, _AWS_AKIA_RE, _GOOGLE_API_RE, _SLACK_RE,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redactor_enabled() -> bool:
    return os.environ.get("PERCEPTION_REDACTOR_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _floor_detects_secret(text: str | None) -> bool:
    """The authoritative secret detector: the shared CLI redaction patterns PLUS the
    perception-specific env-assignment / PEM / cloud-key shapes."""
    if not text:
        return False
    if contains_secret(text):
        return True
    return any(rx.search(text) for rx in _EXTRA_SECRET_RES)


class RedactionError(Exception):
    """Any condition that forces a fail-closed withhold."""


@dataclass(frozen=True)
class DetectedRegion:
    box: tuple[int, int, int, int]
    text: str = ""
    confidence: float = 1.0
    kind: str = "text"


class RedactorEngine(Protocol):
    def detect(self, image_bytes: bytes, *, width: int, height: int) -> list[DetectedRegion]:
        ...


@dataclass
class _ClassifyResult:
    redact_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    withhold: bool = False
    reasons: list[str] = field(default_factory=list)
    region_count: int = 0


@dataclass
class RedactionOutcome:
    status: str  # planner_safe | withheld | gone
    reasons: list[str] = field(default_factory=list)
    redact_count: int = 0


# ── alpha-safe, image-bomb-guarded decode ────────────────────────────────────

def _decode_guarded(raw: bytes):
    """Decode behind hard caps, reject multi-frame inputs, and alpha-flatten over an
    opaque background. Dimensions are checked from the header BEFORE the full pixel
    decode, so a decompression bomb is rejected cheaply. Returns an opaque RGB image."""
    from PIL import Image

    if not raw:
        raise RedactionError("empty image")
    if len(raw) > MAX_INPUT_BYTES:
        raise RedactionError(f"image too large ({len(raw)} bytes)")
    try:
        img = Image.open(io.BytesIO(raw))
        width, height = img.size  # header-only; no full decode yet
    except Exception as exc:  # noqa: BLE001
        raise RedactionError(f"image open failed: {exc}") from exc
    if width <= 0 or height <= 0 or width > MAX_DIM or height > MAX_DIM:
        raise RedactionError(f"image dimensions out of range: {width}x{height}")
    if width * height > MAX_PIXELS:
        raise RedactionError(f"image pixel count too large: {width}x{height}")
    if getattr(img, "n_frames", 1) > 1:
        # APNG / multi-frame: we only redact frame 0 — a secret on a later frame
        # would survive. Fail-closed (screencaptures are single-frame).
        raise RedactionError("multi-frame image not supported")
    try:
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise RedactionError(f"image decode failed: {exc}") from exc
    return _flatten_opaque(img)


def _flatten_opaque(img):
    """Composite onto an opaque black background, dropping any alpha. Crucially this
    does NOT use ``convert('RGB')`` directly — that keeps the RGB of fully
    transparent pixels and could REVEAL a secret hidden under transparency. Alpha
    compositing renders exactly what was visible (transparent ⇒ background)."""
    from PIL import Image

    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    return img.convert("RGB")


# ── deterministic floor (authoritative) ──────────────────────────────────────

def _classify_regions(regions: list[DetectedRegion]) -> _ClassifyResult:
    """Decide which boxes to redact and whether to withhold. The floor patterns are
    the sole authority; the engine only proposes regions. Uncertainty ⇒ withhold."""
    out = _ClassifyResult(region_count=len(regions))
    localized_secret_count = 0
    for r in regions:
        if r.kind in _UNSUPPORTED_KINDS:
            out.withhold = True
            out.reasons.append(f"unsupported_class:{r.kind}")
            continue
        if r.kind in _NONTEXT_SENSITIVE_KINDS:
            out.redact_boxes.append(r.box)
            continue
        if r.kind not in _TEXT_KINDS:
            # An engine-proposed region of a kind we don't recognise: we can't reason
            # about whether it's safe, so fail closed rather than silently passing it.
            # Do not echo the unknown kind into metadata/events; engine labels are not
            # an approved display channel.
            out.withhold = True
            out.reasons.append("unknown_region_kind")
            continue
        if r.text and _floor_detects_secret(r.text):
            x, y, w, h = r.box
            if int(w) < MIN_SECRET_BOX_PX or int(h) < MIN_SECRET_BOX_PX:
                # A secret we can't box (degenerate geometry) ⇒ can't cover it.
                out.withhold = True
                out.reasons.append("uncoverable_secret_box")
                continue
            out.redact_boxes.append(r.box)
            localized_secret_count += 1
            if r.confidence < OCR_CONFIDENCE_THRESHOLD:
                out.withhold = True
                out.reasons.append("low_confidence_secret")
    # Unlocalizable backstop: every secret pattern detectable in the space-joined
    # text must have been localized to a box. If the join surfaces MORE secret
    # matches than we localized, at least one spans regions we couldn't box ⇒
    # withhold. (Counting fixes the prior bug where one localized secret suppressed
    # the check for a second, cross-region one.)
    full_text = " ".join(r.text for r in regions if r.text)
    if _count_secret_matches(full_text) > localized_secret_count:
        out.withhold = True
        out.reasons.append("unlocalizable_secret")
    return out


def _count_secret_matches(text: str) -> int:
    """Number of distinct secret matches across all floor patterns (lower bound)."""
    if not text:
        return 0
    from app.services.cli_orchestrator.redaction import _RULES

    total = 0
    for pattern, _replacement in _RULES:
        total += len(pattern.findall(text))
    for rx in _EXTRA_SECRET_RES:
        total += len(rx.findall(text))
    return total


# ── PNG redaction (flatten + strip metadata) ─────────────────────────────────

def _redact_png(image, boxes: list[tuple[int, int, int, int]]) -> bytes:
    """Burn opaque rectangles over ``boxes`` and re-encode a CLEAN PNG on a fresh RGB
    canvas (drops alpha + every ancillary chunk / metadata block)."""
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
    flat.save(buf, format="PNG")
    return buf.getvalue()


def _atomic_write(abspath: str, data: bytes) -> None:
    """Write 0600 to a temp file, fsync, atomically rename, fsync the parent dir.
    On ANY failure the temp file is unlinked so no half-written orphan is left."""
    parent = os.path.dirname(abspath)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    tmp = f"{abspath}.tmp.{uuid.uuid4().hex}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            # os.write may write FEWER bytes than requested (short write); loop until
            # every byte lands, then verify the on-disk size — a truncated redacted
            # PNG must never be published as planner-safe.
            mv = memoryview(data)
            written = 0
            while written < len(data):
                n = os.write(fd, mv[written:])
                if n <= 0:
                    raise RedactionError(
                        f"short write to redacted temp: wrote {written}/{len(data)} bytes"
                    )
                written += n
            os.fsync(fd)
            on_disk = os.fstat(fd).st_size
            if on_disk != len(data):
                raise RedactionError(
                    f"redacted write size mismatch: {on_disk} != {len(data)}"
                )
        finally:
            os.close(fd)
        os.replace(tmp, abspath)
        try:
            dfd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass  # dir fsync is best-effort (some filesystems disallow)
    except Exception:
        perception_storage._unlink_quiet(tmp)
        raise


# ── transition + claim ───────────────────────────────────────────────────────

def _finish_withheld(
    db: Session,
    artifact_id,
    result: _ClassifyResult | None,
    *,
    reason_override: str | None = None,
) -> RedactionOutcome:
    """Fail-closed terminal for one attempt: revert to not_planner_safe, clear all
    redacted fields, release the claim, record a byte-free withhold audit. Re-loads
    the row after rollback. If the row is ALREADY planner_safe (a prior commit
    actually succeeded under an ambiguous error), it is left untouched."""
    db.rollback()
    art = (
        db.query(PerceptionArtifact)
        .filter(PerceptionArtifact.id == artifact_id)
        .first()
    )
    if art is None:
        return RedactionOutcome(status="gone")
    if art.redaction_status == STATUS_PLANNER_SAFE:
        # A commit succeeded server-side despite an ambiguous client error — do not
        # revert a finalized planner-safe artifact.
        return RedactionOutcome(status="planner_safe")
    reasons = list(result.reasons) if result else []
    if reason_override:
        reasons.append(reason_override)
    art.redaction_status = STATUS_NOT_PLANNER_SAFE
    art.redacted_storage_path = None
    art.redacted_at = None
    art.raw_deleted_at = None
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
    worker_id: str,
    root: str | None = None,
    now: datetime | None = None,
) -> RedactionOutcome:
    """Redact one claimed artifact. Fail-closed end-to-end. On success: a clean
    redacted PNG is written + verified (re-detection finds no secret), the RAW is
    hard-deleted (prerequisite), and the row flips to planner_safe. ``worker_id`` is
    required and fenced (the caller must own the claim)."""
    if not worker_id or not str(worker_id).strip():
        raise ValueError("redact_artifact requires a non-empty worker_id")
    root = root or perception_storage.quarantine_root()
    now = now or _utcnow()
    artifact_id = artifact.id
    # Read the raw from the CANONICAL id-derived path, never the DB-stored
    # storage_path — so a corrupted/traversed DB value can't read cross-tenant /
    # out-of-jail bytes into this artifact's planner-safe output.
    raw_abspath = perception_storage.artifact_abspath(
        artifact.tenant_id, artifact.session_id, artifact.id, root=root
    )
    redacted_rel = perception_storage.redacted_relpath(
        artifact.tenant_id, artifact.session_id, artifact.id
    )
    redacted_abs = perception_storage.redacted_abspath(redacted_rel, root=root)

    try:
        # Bounded read: cap before pulling the whole file into memory.
        try:
            if os.path.getsize(raw_abspath) > MAX_INPUT_BYTES:
                raise RedactionError("raw file exceeds size cap")
        except OSError as exc:
            raise RedactionError(f"raw file unreadable: {exc}") from exc
        with open(raw_abspath, "rb") as fh:
            raw = fh.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise RedactionError("raw file exceeds size cap")

        img = _decode_guarded(raw)
        regions = engine.detect(raw, width=img.size[0], height=img.size[1])
        result = _classify_regions(regions)
        if result.withhold:
            return _finish_withheld(db, artifact_id, result)

        redacted_bytes = _redact_png(img, result.redact_boxes)

        # Re-detection pass on the REDACTED output, run through the FULL classifier:
        # the redacted bytes must classify as completely clean — no surviving secret
        # text, no surviving qr/barcode/unsupported region, no unlocalizable match.
        # A mis-aligned/under-sized box, a partial cover, or a non-text region the
        # engine lied about → the secret survives → withhold. This is what makes
        # "candidate boxes only" safe even when the engine's geometry is wrong.
        verify_result = _classify_regions(
            engine.detect(redacted_bytes, width=img.size[0], height=img.size[1])
        )
        if verify_result.withhold or verify_result.redact_boxes:
            perception_storage._unlink_quiet(redacted_abs)
            return _finish_withheld(db, artifact_id, result, reason_override="secret_survived_redaction")

        # Fence the worker FIRST: lock the row + verify we still own the claim
        # (status redacting + matching claimant) and HOLD the lock through the write
        # + raw-delete + commit — so a reclaimed stale worker can neither overwrite
        # the redacted file nor flip state. (Lock before any filesystem write.)
        locked = _lock_owned_redacting(db, artifact_id, worker_id)
        if locked is None:
            db.rollback()
            return RedactionOutcome(status="withheld", reasons=["lost_claim"])

        _atomic_write(redacted_abs, redacted_bytes)

        # Raw hard-delete is a PREREQUISITE of planner_safe.
        if not perception_storage.delete_raw_bytes(locked, root=root):
            db.rollback()
            perception_storage._unlink_quiet(redacted_abs)
            return _finish_withheld(db, artifact_id, result, reason_override="raw_delete_failed")

        locked.redaction_status = STATUS_PLANNER_SAFE
        locked.redacted_storage_path = redacted_rel
        locked.redacted_at = now
        locked.raw_deleted_at = now
        locked.redact_claimed_at = None
        locked.redact_claimed_by = None
        locked.sha256 = hashlib.sha256(redacted_bytes).hexdigest()
        locked.size_bytes = len(redacted_bytes)
        locked.redaction_meta = {
            "verdict": "planner_safe",
            "region_count": result.region_count,
            "redact_count": len(result.redact_boxes),
            "redactor_version": REDACTOR_VERSION,
            "engine": type(engine).__name__,
        }
        db.add(locked)
        db.commit()
        db.refresh(locked)
        return RedactionOutcome(status="planner_safe", redact_count=len(result.redact_boxes))
    except RedactionError as exc:
        perception_storage._unlink_quiet(redacted_abs)
        return _finish_withheld(db, artifact_id, None, reason_override=f"redaction_error:{exc.__class__.__name__}")
    except Exception as exc:  # noqa: BLE001 — ANY failure is fail-closed
        logger.exception("perception redactor: unexpected failure on %s", artifact_id)
        perception_storage._unlink_quiet(redacted_abs)
        return _finish_withheld(db, artifact_id, None, reason_override=f"error:{type(exc).__name__}")


def _lock_owned_redacting(db: Session, artifact_id, worker_id: str):
    """Row-lock the artifact and return it ONLY if it is still `redacting` AND owned
    by exactly ``worker_id``. Otherwise None (lost the claim). The lock is held until
    the caller commits/rolls back, fencing a reclaimed stale worker out of the
    write+delete+commit window."""
    q = db.query(PerceptionArtifact).filter(PerceptionArtifact.id == artifact_id)
    try:
        q = q.with_for_update()
    except Exception:  # pragma: no cover — sqlite
        pass
    art = q.first()
    if art is None or art.redaction_status != STATUS_REDACTING:
        return None
    # Reject an absent/empty claimant too — two stale workers must not both "match"
    # on a None/"" id.
    if not art.redact_claimed_by or art.redact_claimed_by != worker_id:
        return None
    return art


def claim_next_for_redaction(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
    exclude_ids=None,
) -> PerceptionArtifact | None:
    """Claim the oldest redactable artifact (fresh not_planner_safe, or a stale
    'redacting' row whose lease expired) with ``FOR UPDATE SKIP LOCKED``. Returns the
    claimed row (status 'redacting') or None. ``exclude_ids`` skips artifacts already
    handled this pass — a just-withheld row reverts to not_planner_safe and would
    otherwise be re-claimed immediately (FIFO), burning its whole retry budget in one
    pass instead of one attempt per pass."""
    if not worker_id or not str(worker_id).strip():
        raise ValueError("claim_next_for_redaction requires a non-empty worker_id")
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
    if exclude_ids:
        q = q.filter(~PerceptionArtifact.id.in_(list(exclude_ids)))
    try:
        q = q.with_for_update(skip_locked=True)
    except Exception:  # pragma: no cover — sqlite
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


# ── max-attempts coverage / terminal recovery ────────────────────────────────

def recover_exhausted_redacting(
    db: Session,
    *,
    now: datetime | None = None,
    lease_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
) -> int:
    """Finalize stale `redacting` rows that exhausted their retry budget.

    A worker crash on the FINAL allowed attempt would otherwise leave a row stuck in
    `redacting` forever — `claim_next_for_redaction` won't reclaim it once
    `redact_attempts >= cap`, and nothing reverts it, so it masquerades as in-flight
    work. This reverts such rows (stale lease only, never an actively-leased one) to
    `not_planner_safe` with a terminal, byte-free `max_attempts_exhausted` reason so
    they are observable and TTL-reaped. Fail-closed: never produces planner_safe."""
    now = now or _utcnow()
    timeout = lease_timeout_seconds if lease_timeout_seconds is not None else LEASE_TIMEOUT_SECONDS
    attempts_cap = max_attempts if max_attempts is not None else MAX_ATTEMPTS
    stale_before = now - timedelta(seconds=timeout)
    q = (
        db.query(PerceptionArtifact)
        .filter(
            PerceptionArtifact.deleted_at.is_(None),
            PerceptionArtifact.redaction_status == STATUS_REDACTING,
            PerceptionArtifact.redact_attempts >= attempts_cap,
            (
                PerceptionArtifact.redact_claimed_at.is_(None)
                | (PerceptionArtifact.redact_claimed_at < stale_before)
            ),
        )
        .order_by(PerceptionArtifact.created_at.asc())
    )
    try:
        q = q.with_for_update(skip_locked=True)
    except Exception:  # pragma: no cover — sqlite
        pass
    recovered = 0
    for art in q.all():
        art.redaction_status = STATUS_NOT_PLANNER_SAFE
        art.redacted_storage_path = None
        art.redacted_at = None
        art.raw_deleted_at = None
        art.redact_claimed_at = None
        art.redact_claimed_by = None
        art.redaction_meta = {
            "verdict": "withheld",
            "reasons": ["max_attempts_exhausted"],
            "terminal": True,
            "redactor_version": REDACTOR_VERSION,
        }
        db.add(art)
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def planner_safety_reason(artifact: PerceptionArtifact) -> str:
    """Display-safe, byte-free reason code for an artifact's planner-safety state.

    Lets the P5.4 observe path explain WHY an artifact is (not) planner-safe without
    leaking bytes: ``planner_safe`` | ``redacting`` | ``withheld`` |
    ``redactor_disabled`` (flag off, never processed) | ``pending``."""
    status = artifact.redaction_status
    if status == STATUS_PLANNER_SAFE:
        return "planner_safe"
    if status == STATUS_REDACTING:
        return "redacting"
    meta = artifact.redaction_meta if isinstance(artifact.redaction_meta, dict) else {}
    if meta.get("verdict") == "withheld":
        return "withheld"
    if not redactor_enabled():
        return "redactor_disabled"
    return "pending"


# ── driver (sweep-integrated worker over pending perception_artifacts) ────────

@dataclass
class RedactorRunResult:
    enabled: bool
    reason: str = ""
    processed: int = 0
    planner_safe: int = 0
    withheld: int = 0
    recovered: int = 0


def _default_publish(session_id: str, event_type: str, payload: dict, *, tenant_id: str):
    from app.services.collaboration_events import publish_session_event

    return publish_session_event(session_id, event_type, payload, tenant_id=tenant_id)


# Only byte-free, display-safe keys ever leave the redactor on the session SSE.
_SAFE_EVENT_REASON_MAX = 96


def _emit_redaction_event(artifact_id, session_id, tenant_id, outcome, *, publish=None) -> None:
    """Emit a byte-free perception-redaction status event on the session SSE. The
    payload carries ONLY the resource id, the terminal status, a reason CODE, and a
    redact count — never bytes, paths, OCR text, or box geometry."""
    sink = publish or _default_publish
    status = {
        "planner_safe": STATUS_PLANNER_SAFE,
        "withheld": STATUS_NOT_PLANNER_SAFE,
        "gone": "gone",
    }.get(outcome.status, STATUS_NOT_PLANNER_SAFE)
    reason = ",".join(str(r) for r in (outcome.reasons or [])) or outcome.status
    payload = {
        "resource_type": "screenshot",
        "resource_id": str(artifact_id),
        "redaction_status": status,
        "reason": reason[:_SAFE_EVENT_REASON_MAX],
        "redact_count": int(outcome.redact_count or 0),
    }
    try:
        sink(str(session_id), "perception_redaction", payload, tenant_id=str(tenant_id))
    except Exception:
        logger.exception("perception redactor: failed to emit redaction event for %s", artifact_id)


def run_redactor_once(
    db: Session,
    engine: RedactorEngine | None,
    *,
    worker_id: str,
    batch_size: int = 10,
    now: datetime | None = None,
    publish=None,
) -> RedactorRunResult:
    """One driver pass over pending perception_artifacts.

    Flag OFF (``PERCEPTION_REDACTOR_ENABLED``) or no engine wired → do NOTHING:
    artifacts stay ``not_planner_safe`` and a display-safe reason is returned
    (``redactor_disabled`` / ``no_engine``). Flag ON + engine → finalize
    exhausted-redacting zombies, then claim + redact up to ``batch_size`` artifacts,
    emitting one byte-free status-transition event per processed artifact. Fail-closed
    throughout: the per-artifact `redact_artifact` never produces planner_safe on any
    error/uncertainty."""
    if not worker_id or not str(worker_id).strip():
        raise ValueError("run_redactor_once requires a non-empty worker_id")
    if not redactor_enabled():
        return RedactorRunResult(enabled=False, reason="redactor_disabled")
    if engine is None:
        return RedactorRunResult(enabled=True, reason="no_engine")
    now = now or _utcnow()
    res = RedactorRunResult(enabled=True, reason="ran")
    res.recovered = recover_exhausted_redacting(db, now=now)
    seen: set = set()
    for _ in range(max(1, int(batch_size))):
        artifact = claim_next_for_redaction(db, worker_id=worker_id, now=now, exclude_ids=seen)
        if artifact is None:
            break
        # Capture ownership ids BEFORE redact_artifact (it rolls back / refreshes a
        # re-loaded row, which can detach the passed object); these never change.
        aid, sid, tid = artifact.id, artifact.session_id, artifact.tenant_id
        seen.add(aid)
        res.processed += 1
        outcome = redact_artifact(db, artifact, engine, worker_id=worker_id, now=now)
        if outcome.status == STATUS_PLANNER_SAFE:
            res.planner_safe += 1
        elif outcome.status != "gone":
            res.withheld += 1
        _emit_redaction_event(aid, sid, tid, outcome, publish=publish)
    return res


def _load_engine() -> RedactorEngine | None:
    """The production redactor engine, or None when none is wired. The real local
    OCR/vision engine lands in a later slice; until then the driver is fail-closed
    DORMANT (no planner-safe artifacts) even if the flag is on — design §202."""
    return None


async def redactor_loop(
    interval_seconds: int | None = None,
    *,
    worker_id: str | None = None,
) -> None:
    """In-process redactor driver loop (mirrors ``perception_cleanup.cleanup_loop``).
    DORMANT unless ``PERCEPTION_REDACTOR_ENABLED`` is set AND a real engine is wired.
    Uses the API-only quarantine mount; never runs on an agent runtime. Each
    iteration opens its own session and swallows errors so a transient failure never
    kills the loop."""
    import asyncio

    from app.db.session import SessionLocal

    interval = (
        interval_seconds
        if interval_seconds is not None
        else _int_env("PERCEPTION_REDACTOR_INTERVAL_SECONDS", 30)
    )
    wid = worker_id or f"perception-redactor-{os.getpid()}"
    logger.info(
        "perception redactor driver started (interval=%ss, enabled=%s)",
        interval,
        redactor_enabled(),
    )
    while True:
        try:
            engine = _load_engine()
            if redactor_enabled() and engine is not None:
                db = SessionLocal()
                try:
                    res = run_redactor_once(db, engine, worker_id=wid)
                    if res.processed or res.recovered:
                        logger.info(
                            "perception redactor: processed=%d planner_safe=%d withheld=%d recovered=%d",
                            res.processed, res.planner_safe, res.withheld, res.recovered,
                        )
                finally:
                    db.close()
        except Exception:
            logger.exception("perception redactor loop iteration failed")
        await asyncio.sleep(max(5, interval))
