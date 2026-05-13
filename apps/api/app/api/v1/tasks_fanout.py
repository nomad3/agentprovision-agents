"""
Prototype backend for `ap run` + `ap watch`.

This is the Python side of Phase 1 of the CLI differentiation roadmap
(`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`).

The endpoints accept the dispatch shape produced by the CLI and return
synthetic task lifecycles (queued → running → completed) keyed by task
id. Real Temporal dispatch via `FanoutChatCliWorkflow` (planned for
Phase 1 ship) replaces the in-memory store; the wire contracts stay
the same so the CLI side does not move.

Why an in-memory dict and not a DB-backed scaffold:
  - The CLI flow is the demo. We want a fast, predictable lifecycle
    that does not depend on any other service (Temporal, db migration,
    Ollama warmup). The stub is replaced wholesale once the real
    workflow lands, so investing in persistence here is wasted work.
  - The dict is per-pod and resets on restart. Tasks created on pod A
    are not visible from pod B. That is acceptable for the prototype
    (single-pod local dev); the production endpoint goes through the
    workflow run id which Temporal already persists.

Auth: same JWT bearer as other v1 routes. We do NOT use `/internal/*`
here because this endpoint is hit by the human CLI on the operator's
laptop, not a service-to-service call from MCP or code-worker.
"""

from __future__ import annotations

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


# ── Request / response schemas ─────────────────────────────────────────


class _RunEstimate(BaseModel):
    estimated_duration_seconds: int
    estimated_cost_usd: float
    confidence: str


class _RunChild(BaseModel):
    task_id: str
    provider: str
    # Per-child status, only meaningful in /status responses. Optional
    # here so the response model can be reused for /run too.
    status: Optional[str] = None


class RunFanoutRequest(BaseModel):
    """Payload from `ap run`."""

    prompt: str = Field(..., min_length=1, max_length=20_000)
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None

    # Fallback chain — tried in order; first non-quota-error wins.
    providers: List[str] = Field(default_factory=list)

    # Parallel-dispatch list. Mutually exclusive with `providers` (the
    # CLI enforces this via clap; we re-enforce server-side to catch
    # direct API consumers).
    fanout: List[str] = Field(default_factory=list)

    # `council` | `first-wins` | `all` — controls how fanout children
    # are merged. Ignored when `fanout` is empty.
    merge: str = "council"

    @field_validator("merge")
    @classmethod
    def _validate_merge(cls, v: str) -> str:
        allowed = {"council", "first-wins", "all"}
        if v not in allowed:
            raise ValueError(f"merge must be one of {allowed}, got {v!r}")
        return v

    @field_validator("fanout", "providers")
    @classmethod
    def _strip_provider_names(cls, v: List[str]) -> List[str]:
        # CLI users sometimes paste extra whitespace; tolerate it.
        return [p.strip() for p in v if p and p.strip()]


class RunFanoutResponse(BaseModel):
    task_id: str
    status: str
    children: List[_RunChild] = Field(default_factory=list)
    estimate: Optional[_RunEstimate] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None
    children: List[_RunChild] = Field(default_factory=list)


# ── In-memory task ledger (prototype only) ─────────────────────────────


# task_id → record. Keys are deterministic UUIDs minted at dispatch.
# Records hold the dispatch-time params plus a `created_at` we use to
# derive the synthetic lifecycle:
#   t < 2s     → queued
#   2s ≤ t < 8s → running
#   t ≥ 8s     → completed
# This gives `ap watch` enough states to observe a transition during a
# live demo without sleeping for a real CLI invocation.
_TASKS: dict[str, dict] = {}

_QUEUED_SECS = 2.0
_RUNNING_SECS_TOTAL = 8.0


def _derive_status(created_at: float) -> str:
    elapsed = time.monotonic() - created_at
    if elapsed < _QUEUED_SECS:
        return "queued"
    if elapsed < _RUNNING_SECS_TOTAL:
        return "running"
    return "completed"


def _mint_task_id() -> str:
    # `t_` prefix mirrors the CLI output the design doc shows. Suffix
    # is the first 8 chars of a UUID4 hex — short enough for humans to
    # type when resuming via `ap watch`.
    return f"t_{uuid.uuid4().hex[:8]}"


# ── Routes ────────────────────────────────────────────────────────────


@router.post(
    "/run",
    response_model=RunFanoutResponse,
    summary="Dispatch a durable task (single, fallback chain, or fanout).",
)
def run_fanout(
    body: RunFanoutRequest,
    current_user: User = Depends(get_current_user),
) -> RunFanoutResponse:
    """Dispatch endpoint hit by `ap run`.

    Behavior in the prototype:
      - Mints a parent task_id.
      - If `fanout` is non-empty: also mints one child task_id per
        provider; status of children evolves on the same clock as the
        parent (real impl uses Temporal child workflows).
      - Returns immediately. The CLI either tails `/status` or detaches
        (`--background`).

    Status codes:
      - 200: task dispatched successfully.
      - 400: malformed request (handled by Pydantic before we get here).
      - 401: missing / invalid bearer (handled by `get_current_user`).
    """

    if body.providers and body.fanout:
        # Belt-and-suspenders. clap already rejects this at the CLI; a
        # direct API consumer could still send both.
        raise HTTPException(
            status_code=400,
            detail="Cannot pass both `providers` (fallback chain) and `fanout` (parallel).",
        )

    parent_id = _mint_task_id()
    children: list[_RunChild] = []
    if body.fanout:
        children = [
            _RunChild(task_id=_mint_task_id(), provider=p, status="queued")
            for p in body.fanout
        ]

    now = time.monotonic()
    _TASKS[parent_id] = {
        "prompt": body.prompt,
        "providers": list(body.providers),
        "fanout": list(body.fanout),
        "merge": body.merge,
        "tenant_id": body.tenant_id or str(current_user.tenant_id),
        "user_id": str(current_user.id),
        "created_at": now,
        "children": [
            {"task_id": c.task_id, "provider": c.provider, "created_at": now}
            for c in children
        ],
    }

    # Cheap estimate. Real implementation pulls from
    # `rl_experience_service.estimate_for_state` once that lands.
    n_providers = max(len(body.fanout) or len(body.providers) or 1, 1)
    estimate = _RunEstimate(
        estimated_duration_seconds=8,
        estimated_cost_usd=round(0.12 * n_providers, 4),
        confidence="low",  # prototype — no historical data yet
    )

    return RunFanoutResponse(
        task_id=parent_id,
        status="queued",
        children=children,
        estimate=estimate,
    )


@router.get(
    "/{task_id}/status",
    response_model=TaskStatusResponse,
    summary="Get task status — poll target for `ap watch`.",
)
def task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> TaskStatusResponse:
    """Status endpoint hit by `ap watch` (poll loop in the prototype)."""

    record = _TASKS.get(task_id)
    if not record:
        # 404 also surfaces if the pod restarted between dispatch and
        # watch. The real implementation looks up the workflow run via
        # Temporal; this stub does not survive restarts (documented in
        # the module docstring).
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    # Tenant isolation: the dispatcher recorded `tenant_id` at run-time;
    # caller must match. This is the same posture as `/agents/{id}` etc.
    if record["tenant_id"] != str(current_user.tenant_id):
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    status = _derive_status(record["created_at"])
    children = [
        _RunChild(
            task_id=c["task_id"],
            provider=c["provider"],
            status=_derive_status(c["created_at"]),
        )
        for c in record["children"]
    ]

    result: Optional[str] = None
    if status == "completed":
        # Synthetic result body that demonstrates the council-merge
        # demo from the design doc. Real impl reads from
        # `agent_tasks.result_message`.
        if record["fanout"]:
            providers = ", ".join(record["fanout"])
            result = (
                f"[demo result] Fanout over [{providers}] merged via "
                f"`{record['merge']}`.\n\n"
                f"Consensus: all reviewers converged on the prompt:\n"
                f"  > {record['prompt']}\n\n"
                f"This is a Phase-1-prototype synthetic response. The real "
                f"`FanoutChatCliWorkflow` will return the meta-adjudicator "
                f"output once wired."
            )
        else:
            result = (
                f"[demo result] Completed.\n\n"
                f"Prompt: {record['prompt']}\n\n"
                f"This is a Phase-1-prototype synthetic response."
            )

    return TaskStatusResponse(
        task_id=task_id,
        status=status,
        result=result,
        children=children,
    )


@router.post(
    "/{task_id}/cancel",
    summary="Cancel an in-flight task. (`ap cancel <task_id>`)",
    status_code=204,
    responses={204: {"description": "Cancelled."}, 404: {"description": "Not found."}},
)
def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Cancel endpoint for the CLI's eventual `ap cancel`. In the
    prototype we just drop the record; real impl issues
    `RequestCancelWorkflowExecution` to Temporal."""

    record = _TASKS.get(task_id)
    if not record or record["tenant_id"] != str(current_user.tenant_id):
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    _TASKS.pop(task_id, None)
