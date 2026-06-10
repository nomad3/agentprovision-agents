"""Luna Phase 5.2 — governed perception quarantine storage.

Stores governed screenshot bytes on an **API-only** volume
(``OBSERVATION_QUARANTINE_ROOT``, default ``/var/agentprovision/observations``)
that is mounted ONLY on the ``api`` service — never the agent-shared
``workspaces`` volume that code-worker / CLI runtimes can read. This is what
makes P5.2's "no-read by construction" real: the bytes are not on any path an
agent runtime can reach, and there is no retrieval route serving them.

The bytes are write-once, short-TTL, and deleted by the PR4 cleanup. This module
only writes + indexes them; nothing in P5.2 reads them back.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.perception_artifact import PerceptionArtifact

logger = logging.getLogger(__name__)

# A macOS bundle id is reverse-DNS. Constrain it HARD: it is echoed onto the
# byte-free SSE reference, so a free-form value would be an exfil channel (a
# compromised renderer could smuggle base64/OCR chunks through it). The cap also
# keeps it well under the column width so an insert can never fail post-write.
_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# PNG signature — the only accepted observation byte format (verified on the
# actual bytes, never trusting the client content-type).
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# API-only quarantine root. Overridable per env (compose / Helm); the default is
# a path that is intentionally NOT the workspaces volume.
_QUARANTINE_ROOT_ENV = "OBSERVATION_QUARANTINE_ROOT"
_DEFAULT_QUARANTINE_ROOT = "/var/agentprovision/observations"

# Hard short TTL (minutes) and a max accepted size. Env-overridable.
DEFAULT_TTL_MINUTES = int(os.environ.get("PERCEPTION_ARTIFACT_TTL_MINUTES", "15"))
MAX_SCREENSHOT_SIZE = int(os.environ.get("MAX_SCREENSHOT_SIZE_BYTES", str(8 * 1024 * 1024)))

# P5.2 never validates pixels — every artifact is explicitly not planner-safe.
REDACTION_STATUS_TRANSPORT = "not_planner_safe"


class PerceptionStorageError(Exception):
    """Raised when an artifact cannot be safely stored (fail-closed)."""


def quarantine_root() -> str:
    return os.environ.get(_QUARANTINE_ROOT_ENV, _DEFAULT_QUARANTINE_ROOT)


def artifact_relpath(tenant_id, session_id, artifact_id) -> str:
    """Tenant+session-scoped relative path. Pure (no IO) for unit testing.

    UUIDs are stringified and used as path segments; they cannot contain path
    separators or ``..``, so there is no traversal surface.
    """
    return os.path.join(str(tenant_id), str(session_id), f"{artifact_id}.png")


def artifact_abspath(tenant_id, session_id, artifact_id, *, root: str | None = None) -> str:
    base = root or quarantine_root()
    return os.path.join(base, artifact_relpath(tenant_id, session_id, artifact_id))


def save_observation_artifact(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    shell_id: str,
    device_id: uuid.UUID | None,
    data: bytes,
    source_window_bundle_id: str | None = None,
    ttl_minutes: int | None = None,
    max_size_bytes: int | None = None,
) -> PerceptionArtifact:
    """Write redacted screenshot bytes to the quarantine + register the row.

    Fail-closed: empty/oversized payloads raise before anything is written; a
    write failure raises and persists no row.
    """
    # Validate EVERYTHING that could otherwise fail the insert post-write, BEFORE
    # touching the disk (no orphan bytes), and reject the exfil channel.
    size = len(data)
    cap = max_size_bytes if max_size_bytes is not None else MAX_SCREENSHOT_SIZE
    if size == 0:
        raise PerceptionStorageError("empty observation payload")
    if size > cap:
        raise PerceptionStorageError(f"observation too large ({size} > {cap})")
    if not data.startswith(PNG_MAGIC):
        raise PerceptionStorageError("observation is not a PNG")
    if source_window_bundle_id is not None and not _BUNDLE_ID_RE.match(source_window_bundle_id):
        raise PerceptionStorageError("invalid source_window_bundle_id")

    artifact_id = uuid.uuid4()
    abspath = artifact_abspath(tenant_id, session_id, artifact_id)
    relpath = artifact_relpath(tenant_id, session_id, artifact_id)
    try:
        # 0700 dirs so only the api process user can read the quarantine tree.
        os.makedirs(os.path.dirname(abspath), mode=0o700, exist_ok=True)
        # Write 0600, write-once.
        fd = os.open(abspath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except OSError as exc:
        raise PerceptionStorageError(f"quarantine write failed: {exc}") from exc

    ttl = ttl_minutes if ttl_minutes is not None else DEFAULT_TTL_MINUTES
    artifact = PerceptionArtifact(
        id=artifact_id,
        tenant_id=tenant_id,
        session_id=session_id,
        shell_id=shell_id,
        device_id=device_id,
        artifact_type="screenshot",
        storage_path=relpath,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=size,
        redaction_status=REDACTION_STATUS_TRANSPORT,
        source_window_bundle_id=source_window_bundle_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ttl),
    )
    try:
        db.add(artifact)
        db.flush()
    except Exception:
        # No untracked bytes: unlink the just-written file if the row fails.
        _unlink_quiet(abspath)
        raise
    return artifact


def _unlink_quiet(abspath: str) -> None:
    try:
        os.remove(abspath)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # Don't fail the caller, but make orphan bytes operator-visible (e.g. a
        # readonly fs / NFS stale handle) — silently swallowing leaves untracked
        # bytes that the "no untracked bytes" contract claims can't exist.
        logger.warning("perception storage: could not unlink orphan bytes at %s: %s", abspath, exc)


def unlink_artifact_bytes(artifact: PerceptionArtifact, *, root: str | None = None) -> None:
    """Best-effort unlink of an artifact's bytes (no DB write). Used to avoid
    orphan bytes when the surrounding transaction fails after the file write."""
    _unlink_quiet(os.path.join(root or quarantine_root(), str(artifact.storage_path)))


def expired_artifacts(db: Session, *, now: datetime | None = None, limit: int = 500):
    """Live (not-yet-deleted) artifacts past TTL — the PR4 cleanup scan."""
    cutoff = now or datetime.now(timezone.utc)
    return (
        db.query(PerceptionArtifact)
        .filter(
            PerceptionArtifact.deleted_at.is_(None),
            PerceptionArtifact.expires_at <= cutoff,
        )
        .limit(limit)
        .all()
    )


def hard_delete_artifact(db: Session, artifact: PerceptionArtifact, *, root: str | None = None) -> bool:
    """Unlink the bytes + mark the row deleted. Idempotent; best-effort unlink."""
    abspath = os.path.join(root or quarantine_root(), str(artifact.storage_path))
    try:
        os.remove(abspath)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    artifact.deleted_at = datetime.now(timezone.utc)
    db.add(artifact)
    return True
