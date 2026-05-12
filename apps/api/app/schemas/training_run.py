"""Pydantic shapes for /memory/training/* endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# Wedge sources mirror the design doc §3 list. Kept as a Literal so
# FastAPI emits a proper enum in the OpenAPI schema (the SPA + the
# CLI bindings get strict typing) and so the endpoint rejects unknown
# sources before any DB write.
Source = Literal[
    "local_ai_cli", "github_cli", "gmail", "calendar", "slack", "whatsapp"
]


class BulkIngestRequest(BaseModel):
    """Payload for `POST /memory/training/bulk-ingest`.

    `items` carries the raw, source-specific records — the workflow's
    extract activity normalizes them into entities/observations. The
    server intentionally doesn't validate item shape here: each source
    adapter (PR-Q3a/b, PR-Q4/5) knows its own format, and we want to
    keep this endpoint stable across source schema changes.
    """

    source: Source
    items: List[Dict[str, Any]] = Field(
        ...,
        max_length=10_000,
        description="Raw source records — gmail messages, gh repos, claude sessions, etc.",
    )
    snapshot_id: uuid.UUID = Field(
        ...,
        description=(
            "Client-generated idempotency key. POSTing the same "
            "(tenant_id, snapshot_id) twice returns the existing "
            "training_run without spawning a parallel workflow."
        ),
    )


class TrainingRunResponse(BaseModel):
    """`GET /memory/training/{run_id}` shape."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    source: str
    snapshot_id: uuid.UUID
    status: Literal["pending", "running", "complete", "failed"]
    items_total: int
    items_processed: int
    progress_fraction: Optional[float] = Field(
        None, description="0.0–1.0; null if items_total is 0 (workflow hasn't reported)."
    )
    error: Optional[str] = None
    workflow_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BulkIngestResponse(BaseModel):
    """`POST /memory/training/bulk-ingest` response.

    Returns the run row directly so the caller can short-circuit on
    `status=complete` (idempotent replay) and skip subscribing to the
    SSE progress stream.
    """

    run: TrainingRunResponse
    estimated_seconds: int = Field(
        ...,
        description="Rough ETA = items / 20 batches × 3s per batch. UI hint only.",
    )
    deduplicated: bool = Field(
        ...,
        description="True when the (tenant_id, snapshot_id) already existed — no new workflow was started.",
    )
