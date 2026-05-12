"""TrainingIngestionWorkflow — runs initial training for `ap quickstart`.

Walks the raw items the caller posted to `/memory/training/bulk-ingest`,
batches them into chunks of 20, and for each batch fires an
`extract_and_persist_batch` activity that pulls entities/observations
out via the existing `knowledge_extraction` service and writes them to
the knowledge graph.

The workflow updates the `training_runs` row after each batch so the
SSE progress stream (PR-Q1b) and the `GET /memory/training/{id}`
polling endpoint reflect live state.

Why a Temporal workflow rather than an inline FastAPI background task:
    - Each batch can take 3-10s (Gemma extraction). Inline would block
      the API request for minutes.
    - Idempotent retries on activity failure for free (one bad item
      doesn't kill the whole snapshot).
    - Heartbeats keep tenant-scoped progress queryable even if the
      worker pod restarts mid-run.

See: docs/plans/2026-05-11-ap-quickstart-design.md §7.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

from temporalio import activity, workflow

# Default batch size — same as the inbox-monitor bulk path. 20 items per
# Gemma extraction call hits a sweet spot between latency (each batch
# returns in ~3s) and tenancy fairness (no single training pass starves
# the orchestration queue for minutes).
_BATCH_SIZE = 20


@dataclass
class TrainingIngestionInput:
    run_id: str
    tenant_id: str
    source: str
    snapshot_id: str
    items: List[Dict[str, Any]] = field(default_factory=list)


# ── Activities ─────────────────────────────────────────────────────


@activity.defn
async def extract_and_persist_batch(
    run_id: str,
    tenant_id: str,
    source: str,
    batch_index: int,
    items: List[Dict[str, Any]],
) -> int:
    """Extract entities from `items` and upsert into the knowledge graph.

    Returns the count of items successfully processed (≤ len(items)) so
    the workflow can advance `training_runs.items_processed` precisely
    even when a subset of items fails to parse.

    PR-Q1 scope: minimum-viable wiring. Each source-specific adapter
    (PR-Q3a/b, PR-Q4, PR-Q5) will replace the placeholder body with
    its own normalization step that turns raw `items` into
    `knowledge_extraction.extract_from_content` calls.
    """
    # Lazy import inside the activity body so the workflow process
    # (which never imports app.db.session) doesn't pay the import cost.
    from app.db.session import SessionLocal
    from app.db.safe_ops import safe_rollback

    db = SessionLocal()
    processed = 0
    try:
        # Stub body — the real implementation lives in each wedge PR.
        # We touch the DB intentionally so the activity exercises the
        # tenancy + session boundary in tests, but skip the actual
        # extract until the source-adapter PRs land.
        from app.models.training_run import TrainingRun
        import uuid as _uuid

        run = db.query(TrainingRun).filter(TrainingRun.id == _uuid.UUID(run_id)).first()
        if run is None:
            activity.logger.warning("training_run %s vanished mid-flight — skipping batch", run_id)
            return 0

        processed = len(items)
        run.items_processed = (run.items_processed or 0) + processed
        db.commit()

        activity.heartbeat(
            f"batch {batch_index} processed: tenant={tenant_id[:8]} +{processed}"
        )
        return processed
    except Exception:
        safe_rollback(db)
        activity.logger.exception("extract_and_persist_batch failed")
        raise
    finally:
        db.close()


@activity.defn
async def finalize_training_run(run_id: str, succeeded: bool, error: str = "") -> None:
    """Stamp the `training_runs` row with terminal state. Run on the
    happy path AND the workflow-failure path so the user-visible
    status never lingers at `running` after the workflow exits."""
    from datetime import datetime as _dt
    import uuid as _uuid

    from app.db.safe_ops import safe_rollback
    from app.db.session import SessionLocal
    from app.models.training_run import TrainingRun

    db = SessionLocal()
    try:
        run = db.query(TrainingRun).filter(TrainingRun.id == _uuid.UUID(run_id)).first()
        if run is None:
            return
        run.status = "complete" if succeeded else "failed"
        run.completed_at = _dt.utcnow()
        if error:
            run.error = error[:2000]  # bound the string before psycopg2 chokes
        db.commit()
    except Exception:
        safe_rollback(db)
        activity.logger.exception("finalize_training_run failed")
    finally:
        db.close()


# ── Workflow ───────────────────────────────────────────────────────


@workflow.defn(name="TrainingIngestionWorkflow")
class TrainingIngestionWorkflow:
    @workflow.run
    async def run(self, input: TrainingIngestionInput) -> Dict[str, Any]:
        items = input.items or []
        total = len(items)
        succeeded = 0
        last_error = ""

        # Iterate in deterministic batch order so resume-from-failure
        # picks up exactly where we left off (Temporal workflow history
        # is replay-safe; bare `for i, b in enumerate(...)` is fine).
        for batch_index in range(0, total, _BATCH_SIZE):
            batch = items[batch_index : batch_index + _BATCH_SIZE]
            try:
                processed = await workflow.execute_activity(
                    extract_and_persist_batch,
                    args=[
                        input.run_id,
                        input.tenant_id,
                        input.source,
                        batch_index // _BATCH_SIZE,
                        batch,
                    ],
                    # 60s per batch is generous; Gemma extraction on the
                    # M4 GPU runs in ~3s per 20-item batch. The bound is
                    # there to surface a stuck batch rather than silently
                    # block the workflow forever.
                    start_to_close_timeout=timedelta(seconds=60),
                    heartbeat_timeout=timedelta(seconds=30),
                )
                succeeded += processed or 0
            except Exception as exc:
                # One bad batch doesn't fail the whole snapshot — log it
                # and keep going so the user sees partial progress
                # rather than a binary success/fail. The terminal
                # `error` field captures the last problem for forensics.
                last_error = str(exc)[:500]
                workflow.logger.exception("training batch %s failed", batch_index)

        terminal_ok = succeeded > 0 and not last_error
        await workflow.execute_activity(
            finalize_training_run,
            args=[input.run_id, terminal_ok, last_error],
            start_to_close_timeout=timedelta(seconds=15),
        )

        return {
            "run_id": input.run_id,
            "total": total,
            "succeeded": succeeded,
            "error": last_error or None,
        }
