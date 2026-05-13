"""
Prototype backend for `ap run` + `ap watch`.

Python side of Phase 1 of the CLI differentiation roadmap
(`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`).

The endpoints accept the dispatch shape produced by the CLI and return
synthetic task lifecycles (queued → running → completed | failed |
cancelled) keyed by task id. Real Temporal dispatch via
`FanoutChatCliWorkflow` (planned for Phase 1 ship) replaces the
in-memory store; the wire contracts stay the same so the CLI side
does not move.

Why an in-memory dict and not a DB-backed scaffold:
  - The CLI flow is the demo. We want a fast, predictable lifecycle
    that does not depend on any other service (Temporal, db migration,
    Ollama warmup). The stub is replaced wholesale once the real
    workflow lands, so investing in persistence here is wasted work.
  - State is **per-worker, per-pod**, in-memory, non-durable. With
    `uvicorn --workers N>1` or gunicorn, each worker has its own
    `_TASKS` dict, so a task dispatched on worker A is not visible
    from worker B — pin replica count to 1 OR run with a single
    worker process during the prototype window.

Eviction (round-1 H1 — DoS bound on memory):
  - Per-tenant cap of `MAX_TASKS_PER_TENANT` in-flight task records
    (parent + children counted separately). Exceeding the cap returns
    `429 Too Many Requests`.
  - Opportunistic wall-clock TTL sweep on every dispatch: records
    older than `TASK_TTL_SECONDS` are evicted. No background thread —
    sweep runs inline on the request path so we don't fight uvicorn's
    event loop.

Auth: standard JWT bearer via `get_current_user`. We do NOT use
`/internal/*` here because this endpoint is hit by the human CLI on
the operator's laptop, not a service-to-service call from MCP or
code-worker.

Tenant spoofing protection (round-1 B1):
  - `tenant_id` of every stored task is bound to the JWT — never to
    request-body fields. The CLI's `--tenant` flag is also removed
    pending the `ap tenant use` ergonomics (design open question #4).
  - `agent_id` and `session_id` in the body are not yet validated for
    tenant-ownership here because the prototype dispatch does not
    consume them downstream. They are stored on the record so the
    real `FanoutChatCliWorkflow` can pick them up; that workflow
    runs its own ownership check before any tool call, which is the
    correct gate (it sees the full Agent + ChatSession contexts).
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


# ── Request / response schemas ─────────────────────────────────────────


class RunEstimate(BaseModel):
    estimated_duration_seconds: int
    estimated_cost_usd: float
    confidence: str


class RunChildDispatch(BaseModel):
    """Child returned by `POST /run` — minted IDs + provider only.

    Split out from `RunChildStatus` (round-1 M3) so future fields on
    one shape don't leak into the other.
    """

    task_id: str
    provider: str


class RunChildStatus(BaseModel):
    """Child returned by `GET /{id}/status` — adds per-child status.

    Forward-compatible: `error` will land here when failure paths
    materialize (round-1 M2 lands on the parent's `TaskStatusResponse`;
    children inherit the same shape in a follow-up).
    """

    task_id: str
    provider: str
    status: str


class RunFanoutRequest(BaseModel):
    """Payload from `ap run`.

    Tenant binding (round-1 B1): tenant identity is taken from the
    JWT — NOT from this body. We deliberately do NOT carry a
    `tenant_id` field; any tenant override needs `ap tenant use`
    semantics (design open question #4) which are out of scope here.
    """

    prompt: str = Field(..., min_length=1, max_length=20_000)
    agent_id: Optional[str] = None
    session_id: Optional[str] = None

    # Fallback chain — tried in order; first non-quota-error wins.
    providers: List[str] = Field(default_factory=list)

    # Parallel-dispatch list. Mutually exclusive with `providers` —
    # enforced both at the schema level (round-1 M4, model_validator
    # below) and again in the route handler as belt-and-suspenders.
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
        # Round-1 N4: CLI users (and direct API consumers) sometimes
        # paste `",claude, ,codex"` from a comma-split. Drop empty /
        # whitespace-only entries silently — this is documented
        # leniency, not a bug. Pass a clean comma-split list if you
        # want strict validation.
        return [p.strip() for p in v if p and p.strip()]

    @model_validator(mode="after")
    def _exclusive_providers_or_fanout(self) -> "RunFanoutRequest":
        """Round-1 M4: schema-level rejection of `providers ∧ fanout`.

        Produces a 422 with field paths instead of the route's free-form
        400 + detail string, matching FastAPI / Pydantic conventions
        for direct API consumers.
        """
        if self.providers and self.fanout:
            raise ValueError(
                "providers and fanout are mutually exclusive — pass one or neither"
            )
        return self


class RunFanoutResponse(BaseModel):
    task_id: str
    status: str
    children: List[RunChildDispatch] = Field(default_factory=list)
    estimate: Optional[RunEstimate] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None
    # Round-1 M2: surface failure reason on `failed`/`cancelled` so
    # the CLI can render something other than "[ap] t_xxx — failed"
    # with no context. Stays `None` on `completed` / `running` /
    # `queued`. Free-form for the prototype; the real impl returns
    # a structured `{code, message, retryable}` discriminator.
    error: Optional[str] = None
    children: List[RunChildStatus] = Field(default_factory=list)


# ── In-memory task ledger (prototype only) ─────────────────────────────


# task_id → record. Keys are deterministic UUIDs minted at dispatch.
# Records hold dispatch-time params plus a `created_at` we use to
# derive the synthetic lifecycle:
#   t < QUEUED_SECS         → queued
#   t < RUNNING_SECS_TOTAL  → running
#   t ≥ RUNNING_SECS_TOTAL  → completed
# Round-1 N2: constants are public-by-convention (uppercase, no
# underscore prefix) matching scoring_rubrics.py / auto_quality_scorer.py.
_TASKS: dict[str, dict] = {}

# Round-2 N2-1: maintain an O(1) tenant-count alongside _TASKS so the
# cap check at dispatch is constant-time instead of O(n). Keys are
# tenant_id strings; values are the live record count for that tenant.
# Every mutation that touches `tenant_id` on a record (insert, evict,
# cancel) must update this map in lock-step.
_TENANT_COUNTS: dict[str, int] = defaultdict(int)

QUEUED_SECS = 2.0
RUNNING_SECS_TOTAL = 8.0

# Round-1 H1: DoS bound. MAX_TASKS_PER_TENANT is high enough for any
# normal interactive use, low enough that a misbehaving tenant cannot
# OOM the pod. TASK_TTL_SECONDS gives a 10-minute window after which
# a completed task disappears from /status (the real impl swaps to
# Temporal which already has its own visibility window).
MAX_TASKS_PER_TENANT = 50
TASK_TTL_SECONDS = 600.0


def _derive_status(created_at: float) -> str:
    elapsed = time.monotonic() - created_at
    if elapsed < QUEUED_SECS:
        return "queued"
    if elapsed < RUNNING_SECS_TOTAL:
        return "running"
    return "completed"


def _mint_task_id() -> str:
    """Mint a task id.

    Round-1 H2: 16 hex chars (64-bit entropy) instead of 8 (32-bit).
    Still typeable for humans resuming via `ap watch`, but 65K× safer
    against collision in the real impl that replaces this stub
    (which will see thousands of concurrent tasks per tenant per day).
    """
    return f"t_{uuid.uuid4().hex[:16]}"


def _evict_record(task_id: str) -> None:
    """Pop a record and decrement the tenant counter in lock-step.
    All eviction paths (`_sweep_expired_tasks`, `cancel_task`,
    child-clean-on-cancel) go through here so the counter never drifts."""
    rec = _TASKS.pop(task_id, None)
    if rec is not None:
        tid = rec.get("tenant_id")
        if tid and _TENANT_COUNTS.get(tid, 0) > 0:
            _TENANT_COUNTS[tid] -= 1
            if _TENANT_COUNTS[tid] == 0:
                # Defensive: prevent the defaultdict from growing
                # unboundedly with stale tenant keys at 0.
                del _TENANT_COUNTS[tid]


def _sweep_expired_tasks() -> int:
    """Round-1 H1: opportunistic TTL sweep. Called inline at every
    dispatch — no background thread, no event-loop fight. Returns the
    number of records evicted (for tests / log lines)."""
    now = time.monotonic()
    expired = [
        tid
        for tid, rec in _TASKS.items()
        if now - rec["created_at"] >= TASK_TTL_SECONDS
    ]
    for tid in expired:
        _evict_record(tid)
    return len(expired)


def _count_tenant_tasks(tenant_id: str) -> int:
    """Round-1 H1 + round-2 N2-1: per-tenant active record count.
    O(1) via the `_TENANT_COUNTS` mirror map maintained on every
    insert / evict / cancel."""
    return _TENANT_COUNTS.get(tenant_id, 0)


def _recount_tenant_tasks_from_records(tenant_id: str) -> int:
    """Round-3 N3-1: O(n) recount of records for a tenant by walking
    `_TASKS`. This is the slow ground-truth that `_TENANT_COUNTS`
    mirrors. Used **only** in tests to assert the counter never
    drifts from the dict. Do NOT call from request paths."""
    return sum(1 for rec in _TASKS.values() if rec["tenant_id"] == tenant_id)


# ── Routes ────────────────────────────────────────────────────────────


@router.post(
    "/run",
    response_model=RunFanoutResponse,
    summary="Dispatch a durable task (single, fallback chain, or fanout).",
)
def run_fanout(
    body: RunFanoutRequest,
    current_user: User = Depends(get_current_user),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
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
      - 422: malformed request (Pydantic) — incl. `providers ∧ fanout`.
      - 401: missing / invalid bearer (handled by `get_current_user`).
      - 429: tenant exceeded `MAX_TASKS_PER_TENANT` in-flight cap.
    """

    # Tenant identity is JWT-bound. Round-1 B1: we deliberately do not
    # accept a body field for this; it is the JWT's tenant or nothing.
    tenant_id = str(current_user.tenant_id)

    # Round-2 M2-1: codify the JWT-only contract. If a client sends
    # `X-Tenant-Id`, it MUST equal the JWT-bound tenant. The CLI's
    # `ApiClient` currently attaches this header on every request from
    # `config.toml`; mismatches mean the local config has drifted
    # from the active session (e.g. login against a new tenant
    # without `ap config clean`). Reject with 400 so the user fixes
    # it instead of silently relying on JWT-wins-by-precedence.
    # Round-3 L3-2: treat a whitespace-only header as not-set (matches
    # the empty-string behavior FastAPI already gives us for blank
    # values). Avoids a confusing 400 on a hand-edited config that
    # happens to leave an indented blank line.
    _header_tenant = (x_tenant_id or "").strip()
    if _header_tenant and _header_tenant != tenant_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "X-Tenant-Id header does not match the JWT tenant. "
                "Re-login against the intended tenant or clear the "
                "stale tenant_id from your CLI config."
            ),
        )

    # Belt-and-suspenders mutual-exclusion check. The model_validator
    # on RunFanoutRequest catches this before we reach here for direct
    # API consumers; the clap-side `conflicts_with` catches it for the
    # CLI. We re-check here in case either side is ever bypassed.
    if body.providers and body.fanout:
        raise HTTPException(
            status_code=400,
            detail="Cannot pass both `providers` (fallback chain) and `fanout` (parallel).",
        )

    # Round-1 H1: opportunistic eviction then cap check.
    _sweep_expired_tasks()
    n_new = 1 + len(body.fanout)  # parent + children we are about to mint
    if _count_tenant_tasks(tenant_id) + n_new > MAX_TASKS_PER_TENANT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Tenant has too many in-flight tasks "
                f"(max {MAX_TASKS_PER_TENANT}). Wait for some to complete or "
                f"call POST /{{task_id}}/cancel."
            ),
        )

    parent_id = _mint_task_id()
    children: list[RunChildDispatch] = []
    if body.fanout:
        children = [
            RunChildDispatch(task_id=_mint_task_id(), provider=p) for p in body.fanout
        ]

    # Round-3 M3-1: write records FIRST, then increment the counter,
    # so a partial-write exception cannot leave _TENANT_COUNTS inflated
    # (no decrement-on-error gymnastics needed). The cap-check above
    # already gates against running over capacity; uvicorn is
    # single-threaded so we don't race ourselves between the check
    # and the increment.
    now = time.monotonic()
    _TASKS[parent_id] = {
        "prompt": body.prompt,
        "providers": list(body.providers),
        "fanout": list(body.fanout),
        "merge": body.merge,
        # Round-1 B1: tenant is JWT-bound. NEVER honor a body field.
        "tenant_id": tenant_id,
        "user_id": str(current_user.id),
        # Round-1 L4: store agent_id / session_id so /status can echo
        # them back; the real FanoutChatCliWorkflow consumes them.
        "agent_id": body.agent_id,
        "session_id": body.session_id,
        "created_at": now,
        "children": [
            {"task_id": c.task_id, "provider": c.provider, "created_at": now}
            for c in children
        ],
    }
    # Also store each child as a top-level record so the cap-counter
    # bills them, and so a future `/cancel <child_id>` can target a
    # specific provider without enumerating every parent record.
    for c in children:
        _TASKS[c.task_id] = {
            "prompt": body.prompt,
            "tenant_id": tenant_id,
            "user_id": str(current_user.id),
            "agent_id": body.agent_id,
            "session_id": body.session_id,
            "parent_id": parent_id,
            "provider": c.provider,
            "created_at": now,
            "children": [],
            "providers": [],
            "fanout": [],
            "merge": body.merge,
        }
    # All writes complete — now increment the counter in lock-step.
    _TENANT_COUNTS[tenant_id] += n_new

    # Cheap estimate. Real implementation pulls from
    # `rl_experience_service.estimate_for_state` once that lands.
    n_providers = max(len(body.fanout) or len(body.providers) or 1, 1)
    estimate = RunEstimate(
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
        # watch, or if TTL eviction (H1) evicted the record. The real
        # implementation looks up the workflow run via Temporal; this
        # stub does not survive restarts (documented in the module
        # docstring).
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    # Round-1 B1: tenant isolation against the JWT-bound stored value.
    # 404 (not 403) is intentional — do not leak existence to other
    # tenants.
    if record["tenant_id"] != str(current_user.tenant_id):
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    status = _derive_status(record["created_at"])
    children = [
        RunChildStatus(
            task_id=c["task_id"],
            provider=c["provider"],
            status=_derive_status(c["created_at"]),
        )
        for c in record["children"]
    ]

    result: Optional[str] = None
    error: Optional[str] = None
    if status == "completed":
        # Synthetic result body that demonstrates the council-merge
        # demo from the design doc. Real impl reads from
        # `agent_tasks.result_message`.
        if record.get("fanout"):
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

    # Prototype lifecycle never reaches `failed`/`cancelled` from the
    # timer logic. `/cancel` deletes the record outright, so subsequent
    # `/status` returns 404, not "cancelled". The `error` field is on
    # the response schema (round-1 M2) so the real impl can populate
    # it without changing the wire contract.

    return TaskStatusResponse(
        task_id=task_id,
        status=status,
        result=result,
        error=error,
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
    `RequestCancelWorkflowExecution` to Temporal.

    Round-1 B1: tenant isolation enforced before the drop so a caller
    in tenant A cannot delete tenant B's record by guessing its id.

    Round-2 M2-2: when cancelling a **child** task, also remove the
    child from its parent's `children` list so subsequent
    `GET /<parent>/status` doesn't keep computing the child's
    synthetic lifecycle from wall-clock forever."""

    record = _TASKS.get(task_id)
    if not record or record["tenant_id"] != str(current_user.tenant_id):
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    parent_id = record.get("parent_id")
    if parent_id:
        # This is a child being cancelled directly. Surgical removal
        # from the parent's children list so /status no longer reports
        # it. Round-2 M2-2.
        parent = _TASKS.get(parent_id)
        if parent is not None:
            parent["children"] = [
                c for c in parent.get("children", []) if c["task_id"] != task_id
            ]
        _evict_record(task_id)
        return

    # Parent (or single-provider task): drop its own children first,
    # then itself. Preserves the cap-counter invariant — orphan child
    # records would otherwise count against the tenant forever.
    for child in record.get("children", []):
        _evict_record(child["task_id"])
    _evict_record(task_id)
