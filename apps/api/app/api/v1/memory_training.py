"""Initial-training endpoints for the `alpha quickstart` flow.

Routes:
    POST /memory/training/bulk-ingest       — kick off an ingestion (idempotent)
    GET  /memory/training/{run_id}          — poll status
    GET  /memory/training/{run_id}/events/stream — SSE progress (PR-Q1b)

Auth: user Bearer JWT. The internal-key variant would let any in-cluster
caller seed a tenant's knowledge graph with arbitrary content — gate it
to user actions only.

See: docs/plans/2026-05-11-ap-quickstart-design.md §7.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import settings
from app.models.training_run import (
    TRAINING_RUN_SOURCES,
    TrainingRun,
)
from app.models.user import User
from app.schemas.training_run import (
    BulkIngestRequest,
    BulkIngestResponse,
    TrainingRunResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _run_to_response(run: TrainingRun) -> TrainingRunResponse:
    """Centralised serializer — keeps the GET + POST response shapes
    in lock-step. progress_fraction is computed at read time so a
    fresh DB row reflects up-to-date arithmetic."""
    return TrainingRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        source=run.source,
        snapshot_id=run.snapshot_id,
        status=run.status,  # type: ignore[arg-type]
        items_total=run.items_total,
        items_processed=run.items_processed,
        progress_fraction=run.progress_fraction(),
        error=run.error,
        workflow_id=run.workflow_id,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _estimate_seconds(items_total: int) -> int:
    """Rough UI hint. We process ~20 items per batch and each batch is
    ~3s of Gemma extraction on the M4 GPU. Round up so the progress
    bar doesn't promise faster than realistic — under-promise."""
    if items_total <= 0:
        return 0
    batches = (items_total + 19) // 20
    return max(3, batches * 3)


@router.post("/memory/training/bulk-ingest", response_model=BulkIngestResponse)
async def bulk_ingest(
    body: BulkIngestRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> BulkIngestResponse:
    """Kick off (or re-attach to) an initial-training pass.

    Idempotent on `(tenant_id, snapshot_id)`. A client retry of the same
    snapshot returns the existing row without starting a parallel
    workflow — `deduplicated=true` in the response tells the caller it
    was a no-op.
    """
    # Defense-in-depth — the Pydantic Literal also rejects, but a
    # missing source-adapter at workflow dispatch time would surface
    # as a Temporal failure with poor UX; better to 400 here.
    if body.source not in TRAINING_RUN_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown source '{body.source}'",
        )

    # Idempotency lookup. The unique index (tenant_id, snapshot_id) is
    # the contract; this is the cheap pre-check to skip the workflow
    # dispatch when we've already seen this snapshot.
    existing = (
        db.query(TrainingRun)
        .filter(
            TrainingRun.tenant_id == current_user.tenant_id,
            TrainingRun.snapshot_id == body.snapshot_id,
        )
        .first()
    )
    if existing is not None:
        logger.info(
            "training bulk-ingest deduplicated: tenant=%s snapshot=%s run=%s status=%s",
            str(current_user.tenant_id)[:8],
            str(body.snapshot_id)[:8],
            str(existing.id)[:8],
            existing.status,
        )
        return BulkIngestResponse(
            run=_run_to_response(existing),
            estimated_seconds=_estimate_seconds(existing.items_total),
            deduplicated=True,
        )

    # PR-Q4b: server-side bootstrappers for Gmail/Calendar.
    #
    # The web wedges for gmail/calendar can't read the user's
    # filesystem the way the CLI wedges can — the SPA POSTs a single
    # stub item and trusts the server to fetch real data via the
    # tenant's OAuth token. Detect that shape here (source matches
    # AND items is empty OR is a single quickstart-stub) and replace
    # items[] with the bootstrapped fetch BEFORE creating the run
    # row, so `items_total` reflects the real count.
    items_for_run: list = list(body.items)
    if body.source in ("gmail", "calendar"):
        is_stub_only = (
            len(items_for_run) == 0
            or (
                len(items_for_run) == 1
                and items_for_run[0].get("kind") == "quickstart-stub"
            )
        )
        if is_stub_only:
            from app.services.quickstart_bootstrappers import (
                bootstrap_calendar_items,
                bootstrap_gmail_items,
            )
            if body.source == "gmail":
                items_for_run = bootstrap_gmail_items(db, str(current_user.tenant_id))
            else:
                items_for_run = bootstrap_calendar_items(db, str(current_user.tenant_id))
            logger.info(
                "training bulk-ingest bootstrapped %d items from %s for tenant=%s",
                len(items_for_run),
                body.source,
                str(current_user.tenant_id)[:8],
            )
            # Empty bootstrap (no OAuth token, API error, empty inbox)
            # → leave the stub item in place so the run still completes
            # with a "no items recognised" outcome instead of being an
            # empty workflow that fails the `succeeded > 0` terminal
            # check.
            if not items_for_run:
                items_for_run = [
                    {
                        "kind": "quickstart-stub",
                        "channel": body.source,
                        "note": f"server bootstrap returned 0 items for {body.source}",
                    }
                ]

    # Insert the row first so the workflow has something to write
    # progress against. `items_total` is set up front from the payload
    # so the SSE stream can render an accurate progress bar without
    # waiting for the workflow to count.
    run = TrainingRun(
        tenant_id=current_user.tenant_id,
        source=body.source,
        snapshot_id=body.snapshot_id,
        status="pending",
        items_total=len(items_for_run),
        items_processed=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Dispatch the Temporal workflow. We wrap in try/except + rollback
    # the run row on failure so the caller can retry without first
    # cleaning up an orphan "pending" row. The unique index would
    # otherwise force `--force` or a manual DELETE.
    try:
        from temporalio.client import Client

        from app.workflows.training_ingestion import (
            TrainingIngestionInput,
            TrainingIngestionWorkflow,
        )

        client = await Client.connect(settings.TEMPORAL_ADDRESS)
        wf_id = f"training-ingestion-{run.id}"

        await client.start_workflow(
            TrainingIngestionWorkflow.run,
            TrainingIngestionInput(
                run_id=str(run.id),
                tenant_id=str(current_user.tenant_id),
                source=body.source,
                snapshot_id=str(body.snapshot_id),
                items=items_for_run,
            ),
            id=wf_id,
            task_queue="agentprovision-orchestration",
        )

        run.workflow_id = wf_id
        run.status = "running"
        run.started_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
    except Exception as exc:
        # Roll back the run row so retries don't trip the unique index.
        # We DELETE rather than mark failed so the caller's next POST
        # gets a clean attempt — the workflow never actually started.
        logger.exception("training bulk-ingest workflow dispatch failed")
        db.delete(run)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to start training workflow: {exc}",
        )

    logger.info(
        "training bulk-ingest dispatched: tenant=%s source=%s items=%d run=%s",
        str(current_user.tenant_id)[:8],
        body.source,
        run.items_total,
        str(run.id)[:8],
    )
    return BulkIngestResponse(
        run=_run_to_response(run),
        estimated_seconds=_estimate_seconds(run.items_total),
        deduplicated=False,
    )


@router.get("/memory/training/{run_id}", response_model=TrainingRunResponse)
def get_training_run(
    run_id: uuid.UUID = Path(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> TrainingRunResponse:
    """Poll the status of a training run.

    Tenant-scoped — returns 404 for any run that belongs to a different
    tenant, regardless of whether it exists. Same probe-resistance
    pattern as PR-E `agent_tokens/mint`.
    """
    run = db.query(TrainingRun).filter(TrainingRun.id == run_id).first()
    if run is None or str(run.tenant_id) != str(current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training run not found")
    return _run_to_response(run)
