"""Luna P5.3b — planner-safe perception delivery (the ONLY agent-facing read path).

Serves ONLY the redacted derivative of a perception artifact, and only when the
full planner-safe contract holds:

* tenant + session ownership (the requesting user must own the chat session),
* master ``desktop_control_enabled`` re-checked at fetch time (fail-closed —
  this path does NOT inherit the #869 observe/approval gates by accident),
* artifact not deleted and not past its TTL,
* ``redaction_status == planner_safe`` AND ``raw_deleted_at IS NOT NULL``
  (the redactor's prerequisite: raw bytes are proven gone),
* the redacted bytes resolve through the CANONICAL id-derived jailed path
  (``perception_storage.redacted_relpath`` + jail check). The DB-stored
  ``storage_path`` / ``redacted_storage_path`` are NEVER used as filesystem
  authority, so the raw artifact can never be served by construction — there is
  no code path here that can open ``storage_path``.

Every denial carries a stable display-safe code (no paths, no OCR text, no
window titles, no bytes). The Alpha CLI mirrors these codes as a typed enum in
``apps/agentprovision-core/src/desktop.rs``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.perception_artifact import PerceptionArtifact
from app.services import perception_storage
from app.services.desktop_control_service import (
    _ensure_desktop_control_enabled,
    _ensure_session_owned_by_user,
    _publish_display_safe_session_event,
)
from app.services.perception_redactor import STATUS_PLANNER_SAFE

logger = logging.getLogger(__name__)

# Sanity ceiling on the redacted read (the redactor caps its output well below
# this; a row claiming more is treated as corrupt, not read into memory).
MAX_REDACTED_READ_BYTES = 32 * 1024 * 1024


class PerceptionFetchDenialCode(str, Enum):
    """Closed, display-safe denial codes for planner-safe artifact delivery.

    Mirrored by the Alpha CLI typed contract (``PerceptionFetchDenialCode`` in
    ``apps/agentprovision-core/src/desktop.rs``) — keep both in sync.
    """

    DESKTOP_CONTROL_DISABLED = "desktop_control_disabled"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    ARTIFACT_EXPIRED = "artifact_expired"
    ARTIFACT_NOT_PLANNER_SAFE = "artifact_not_planner_safe"
    ARTIFACT_RAW_NOT_DELETED = "artifact_raw_not_deleted"
    ARTIFACT_BYTES_UNAVAILABLE = "artifact_bytes_unavailable"
    ARTIFACT_INTEGRITY_MISMATCH = "artifact_integrity_mismatch"


_DENIAL_HTTP_STATUS = {
    PerceptionFetchDenialCode.DESKTOP_CONTROL_DISABLED: 403,
    PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND: 404,
    PerceptionFetchDenialCode.ARTIFACT_EXPIRED: 410,
    PerceptionFetchDenialCode.ARTIFACT_NOT_PLANNER_SAFE: 409,
    PerceptionFetchDenialCode.ARTIFACT_RAW_NOT_DELETED: 409,
    PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE: 409,
    PerceptionFetchDenialCode.ARTIFACT_INTEGRITY_MISMATCH: 409,
}


def _deny(code: PerceptionFetchDenialCode, reason: str) -> None:
    """Raise a structured, display-safe fetch denial. ``reason`` must already be
    display-safe (fixed strings only — never a path, filename, or content)."""
    raise HTTPException(
        status_code=_DENIAL_HTTP_STATUS[code],
        detail={"code": code.value, "reason": reason},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _ensure_delivery_gates(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    """The fetch-time gates every delivery (status or content) must pass."""
    try:
        # Re-check the MASTER flag at fetch time (fail-closed).
        _ensure_desktop_control_enabled(db, tenant_id)
    except HTTPException:
        _deny(
            PerceptionFetchDenialCode.DESKTOP_CONTROL_DISABLED,
            "desktop control is not enabled for this tenant",
        )
    # Session must exist in this tenant and be owned by the requesting user
    # (404/403 with display-safe details, same as the rest of desktop-control).
    _ensure_session_owned_by_user(db, session_id, tenant_id, user_id)


def _get_scoped_artifact(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    shell_id: str | None,
) -> PerceptionArtifact:
    """Tenant+session(+shell)-scoped lookup. A wrong tenant, wrong session,
    wrong shell, unknown id, or already-deleted artifact are all the SAME
    uniform not-found (no cross-scope existence oracle)."""
    query = db.query(PerceptionArtifact).filter(
        PerceptionArtifact.id == artifact_id,
        PerceptionArtifact.tenant_id == tenant_id,
        PerceptionArtifact.session_id == session_id,
        PerceptionArtifact.deleted_at.is_(None),
    )
    if shell_id:
        query = query.filter(PerceptionArtifact.shell_id == shell_id)
    artifact = query.first()
    if artifact is None:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_NOT_FOUND,
            "perception artifact not found",
        )
    return artifact


def _redaction_meta_summary(artifact: PerceptionArtifact) -> dict[str, Any]:
    """Byte-free projection of redaction_meta (verdict + display-safe reason
    codes only — never snippets, offsets, or box geometry)."""
    meta = artifact.redaction_meta or {}
    reasons = meta.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = []
    return {
        "redaction_verdict": meta.get("verdict"),
        "redaction_reasons": [str(r)[:128] for r in reasons[:8]],
    }


def artifact_status(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    shell_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Display-safe status of one perception artifact (no bytes, no paths)."""
    _ensure_delivery_gates(db, tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    artifact = _get_scoped_artifact(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        artifact_id=artifact_id,
        shell_id=shell_id,
    )
    cutoff = now or _utcnow()
    expires_at = _as_aware_utc(artifact.expires_at)
    expired = bool(expires_at is not None and expires_at <= cutoff)
    raw_deleted = artifact.raw_deleted_at is not None
    redacted_available = (
        not expired
        and artifact.redaction_status == STATUS_PLANNER_SAFE
        and raw_deleted
        and bool(artifact.redacted_storage_path)
    )
    return {
        "artifact_id": str(artifact.id),
        "session_id": str(artifact.session_id),
        "shell_id": artifact.shell_id,
        "artifact_type": artifact.artifact_type,
        "redaction_status": artifact.redaction_status,
        "size_bytes": int(artifact.size_bytes),
        "sha256": artifact.sha256,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "expired": expired,
        "raw_deleted": raw_deleted,
        "redacted_available": redacted_available,
        "source_window_bundle_id": artifact.source_window_bundle_id,
        **_redaction_meta_summary(artifact),
    }


def fetch_planner_safe_bytes(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    shell_id: str | None = None,
    source: str = "alpha",
    now: datetime | None = None,
    root: str | None = None,
) -> tuple[PerceptionArtifact, bytes]:
    """Return the redacted planner-safe bytes for one artifact, or deny with a
    display-safe code. This is the single delivery entrypoint for the Alpha
    user-JWT route AND the MCP internal route — both stay thin over it."""
    _ensure_delivery_gates(db, tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    artifact = _get_scoped_artifact(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        artifact_id=artifact_id,
        shell_id=shell_id,
    )

    cutoff = now or _utcnow()
    expires_at = _as_aware_utc(artifact.expires_at)
    if expires_at is None or expires_at <= cutoff:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_EXPIRED,
            "perception artifact has expired",
        )
    if artifact.redaction_status != STATUS_PLANNER_SAFE:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_NOT_PLANNER_SAFE,
            "perception artifact is not planner-safe",
        )
    if artifact.raw_deleted_at is None:
        # planner_safe without the raw hard-delete proof is an inconsistent row
        # (the redactor sets raw_deleted_at BEFORE flipping status) — fail closed.
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_RAW_NOT_DELETED,
            "raw capture has not been deleted",
        )
    if not artifact.redacted_storage_path:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )

    # Resolve the CANONICAL id-derived jailed path. The DB-stored path string is
    # never the filesystem authority: it must EQUAL the canonical derivation or
    # the artifact is treated as tampered and denied.
    base = root or perception_storage.quarantine_root()
    canonical_rel = perception_storage.redacted_relpath(
        artifact.tenant_id, artifact.session_id, artifact.id
    )
    if str(artifact.redacted_storage_path) != canonical_rel:
        logger.warning(
            "perception delivery: redacted_storage_path mismatch for artifact %s",
            artifact.id,
        )
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )
    abspath = perception_storage._jailed_abspath(base, canonical_rel)
    if abspath is None:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )

    try:
        file_size = os.path.getsize(abspath)
    except OSError:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )
    if file_size == 0 or file_size > MAX_REDACTED_READ_BYTES:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )
    if int(file_size) != int(artifact.size_bytes):
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_INTEGRITY_MISMATCH,
            "redacted bytes failed integrity verification",
        )
    try:
        with open(abspath, "rb") as fh:
            data = fh.read(MAX_REDACTED_READ_BYTES + 1)
    except OSError:
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_BYTES_UNAVAILABLE,
            "redacted bytes are not available",
        )
    if hashlib.sha256(data).hexdigest() != artifact.sha256:
        # The row's sha256 is rewritten by the redactor to the REDACTED bytes'
        # hash on the planner_safe flip — a mismatch means corruption/tampering.
        _deny(
            PerceptionFetchDenialCode.ARTIFACT_INTEGRITY_MISMATCH,
            "redacted bytes failed integrity verification",
        )

    # Byte-free delivery audit on the single session SSE (id/hash/size/source
    # only — never bytes, never paths).
    _publish_display_safe_session_event(
        session_id,
        "resource_referenced",
        {
            "resource_type": "screenshot_planner_safe",
            "resource_id": str(artifact.id),
            "hash": artifact.sha256,
            "size_bytes": int(artifact.size_bytes),
            "redaction_status": artifact.redaction_status,
            "expires_at": expires_at.isoformat(),
            "shell_id": artifact.shell_id,
            "delivered_via": source,
        },
        tenant_id=tenant_id,
    )
    return artifact, data
