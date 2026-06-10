"""Luna Phase 5.2 PR4 — governed-perception quarantine TTL cleanup.

The quarantine volume (``OBSERVATION_QUARANTINE_ROOT``) is **api-only** by design
(no agent runtime mounts it — "no-read by construction"). So the cleanup MUST run
inside the api process, NOT an orchestration-worker Temporal job (which has no
access to the volume). This is an in-process asyncio sweeper: a startup catch-up
plus a periodic scan that hard-deletes expired artifacts and emits a byte-free
``resource_expired`` audit event on the single session SSE.

Without this, expired screenshot bytes persist on the api-pod disk indefinitely
(disk exhaustion + an undeleted at-rest exposure window). Spawned from
``app.main`` on startup.
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.db.session import SessionLocal
from app.services import perception_storage
from app.services.collaboration_events import publish_session_event

logger = logging.getLogger(__name__)

# Frequent by design (the design's daily LearningAudio sweep is far too slow for a
# 15-min access TTL). Env-overridable.
DEFAULT_CLEANUP_INTERVAL_SECONDS = int(
    os.environ.get("PERCEPTION_CLEANUP_INTERVAL_SECONDS", "600")
)


def run_cleanup_once(db) -> int:
    """Hard-delete every expired, not-yet-deleted perception artifact + emit a
    byte-free ``resource_expired`` event. Returns the count deleted. Idempotent
    and best-effort: a missing file or a failed event never aborts the sweep.
    """
    artifacts = perception_storage.expired_artifacts(db)
    if not artifacts:
        return 0
    deleted = 0
    for art in artifacts:
        session_id = str(art.session_id)
        tenant_id = str(art.tenant_id)
        artifact_id = str(art.id)
        if perception_storage.hard_delete_artifact(db, art):
            deleted += 1
            try:
                publish_session_event(
                    session_id,
                    "resource_expired",
                    {"resource_type": "screenshot", "resource_id": artifact_id},
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.exception(
                    "perception cleanup: failed to emit resource_expired for %s",
                    artifact_id,
                )
    db.commit()
    return deleted


async def cleanup_loop(interval_seconds: int = DEFAULT_CLEANUP_INTERVAL_SECONDS) -> None:
    """Startup catch-up + periodic sweep. Each iteration opens its own session,
    swallows errors (so a transient DB/fs failure never kills the loop), and
    sleeps. Runs for the api process lifetime."""
    logger.info(
        "perception cleanup sweeper started (interval=%ss, root=%s)",
        interval_seconds,
        perception_storage.quarantine_root(),
    )
    while True:
        try:
            db = SessionLocal()
            try:
                deleted = run_cleanup_once(db)
                if deleted:
                    logger.info("perception cleanup: deleted %d expired artifact(s)", deleted)
            finally:
                db.close()
        except Exception:
            logger.exception("perception cleanup loop iteration failed")
        await asyncio.sleep(max(30, interval_seconds))
