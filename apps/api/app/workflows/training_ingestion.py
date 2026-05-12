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

    PR-Q4 scope: rule-based extraction for kinds emitted by the
    Q3a (Local AI CLI) and Q3b (GitHub CLI) scanners. Each kind maps
    deterministically onto one or more knowledge entities. Items
    whose `kind` we don't recognise are counted as 'processed' but
    not persisted — better to make progress on the known shapes than
    fail the whole batch on a single unknown kind.

    Future (PR-Q4b/Q5): server-side bootstrappers for Gmail / Calendar
    / Slack / WhatsApp that fetch items from those integrations and
    feed the same `items` shape into this function. Gemma-based free-
    text extraction is deferred — the rule-based path covers the
    structured-source wedges and is fast (no LLM call per item).
    """
    # Lazy imports — the workflow process never touches the DB
    # session directly; only the activity does. Keeps replay fast.
    from app.db.session import SessionLocal
    from app.db.safe_ops import safe_rollback

    db = SessionLocal()
    # Reviewer (PR #408 finding #3) caught that conflating 'seen' with
    # 'persisted' regresses toward the success-without-effect anti-
    # pattern called out in orchestration_cascade_root_cause.md.
    # Counters keep both numbers honest: `persisted` is what actually
    # landed in knowledge_entities; `recognised` includes deferred
    # kinds (github_pr/issue, quickstart-stub) plus persisted; the
    # difference between (recognised + unknown) and items.len() lets
    # the workflow surface unknown-kind drift in a single WARN per
    # batch instead of silently inflating the progress bar.
    persisted = 0
    recognised = 0
    unknown_kinds: Dict[str, int] = {}
    try:
        from app.models.training_run import TrainingRun
        import uuid as _uuid

        run = db.query(TrainingRun).filter(TrainingRun.id == _uuid.UUID(run_id)).first()
        if run is None:
            activity.logger.warning("training_run %s vanished mid-flight — skipping batch", run_id)
            return 0

        tenant_uuid = _uuid.UUID(tenant_id)
        for item in items:
            kind = item.get("kind", "") or "<missing>"
            try:
                outcome = _persist_item(db, tenant_uuid, item)
                if outcome == "persisted":
                    persisted += 1
                    recognised += 1
                elif outcome == "recognised":
                    recognised += 1
                else:
                    # Genuinely unknown kind — accumulate into the
                    # per-batch histogram so a single WARN below
                    # surfaces wire-format drift without flooding logs.
                    unknown_kinds[kind] = unknown_kinds.get(kind, 0) + 1
            except Exception:
                safe_rollback(db)
                activity.logger.exception(
                    "item persist failed (kind=%s) — continuing batch",
                    kind,
                )

        if unknown_kinds:
            # One log line per batch, not per item — keeps log volume
            # bounded even when a misconfigured wedge ships 10k unknowns.
            activity.logger.warning(
                "batch %s: %d unknown-kind items skipped (not persisted): %s",
                batch_index,
                sum(unknown_kinds.values()),
                dict(sorted(unknown_kinds.items())),
            )

        # `items_processed` reflects RECOGNISED items only — the user's
        # progress bar shows what the workflow actually saw and could
        # do something with. Unknown items don't move the bar; they
        # surface as the per-batch WARN above. If the whole snapshot
        # turns out to be unknown, items_processed stays 0 and the
        # caller can present a meaningful 'no items recognised'
        # outcome instead of '10000/10000 succeeded but graph empty'.
        run.items_processed = (run.items_processed or 0) + recognised
        db.commit()

        activity.heartbeat(
            f"batch {batch_index}: tenant={tenant_id[:8]} "
            f"persisted={persisted} recognised={recognised} unknown={sum(unknown_kinds.values())}"
        )
        return recognised
    except Exception:
        safe_rollback(db)
        activity.logger.exception("extract_and_persist_batch failed")
        raise
    finally:
        db.close()


def _persist_item(db, tenant_id, item: Dict[str, Any]) -> str:
    """Map one wedge-emitted item onto a knowledge entity.

    Returns one of three outcome strings so the caller can keep the
    user-visible counters honest:

        "persisted"   — the item was a recognised kind AND a
                        knowledge_entities row was created.
        "recognised"  — the item was a recognised kind but
                        deliberately not persisted in v1 (github_pr /
                        github_issue → deferred to Q4-back-2; the
                        quickstart-stub items that the wedge stubs
                        emit during not-yet-implemented branches).
        "unknown"     — neither — counted into the per-batch unknown
                        histogram so wire-format drift surfaces in
                        logs instead of silently inflating progress.

    Rule table:
      local_user_identity → Person (persisted)
      local_ai_session    → Project keyed on project_path (persisted
                            when project_path is non-empty; recognised
                            otherwise because there's nothing to anchor)
      github_user         → Person (persisted)
      github_repo         → Project (persisted)
      github_org          → Organization (persisted)
      github_pr           → recognised, not persisted (Q4-back-2)
      github_issue        → recognised, not persisted (Q4-back-2)
      quickstart-stub     → recognised, not persisted
    """
    from app.schemas.knowledge_entity import KnowledgeEntityCreate
    from app.services.knowledge import create_entity

    kind = item.get("kind", "")
    if kind == "local_user_identity":
        name = item.get("name") or item.get("email") or "Local user"
        ent = KnowledgeEntityCreate(
            entity_type="person",
            category="user",
            name=name,
            # Bio-only would also work, but local_user_identity items
            # don't carry a bio — keeping email as description for the
            # user-anchor entity is informative without doubling up
            # with the attributes.email field. (github_user has a real
            # bio; that branch prefers bio.)
            description=item.get("email") or None,
            attributes={
                "email": item.get("email"),
                "source": "ap_quickstart_local_ai_cli",
            },
        )
        create_entity(db, ent, tenant_id)
        return "persisted"

    if kind == "local_ai_session":
        project_path = item.get("project_path") or ""
        if not project_path:
            # Recognised kind, but nothing to anchor the Project on.
            return "recognised"
        name = project_path.rstrip("/").split("/")[-1] or project_path
        ent = KnowledgeEntityCreate(
            entity_type="project",
            category="project",
            name=name,
            description=item.get("derived_topic_hint") or None,
            attributes={
                "project_path": project_path,
                "runtime": item.get("runtime"),
                "source": "ap_quickstart_local_ai_cli",
            },
        )
        create_entity(db, ent, tenant_id)
        return "persisted"

    if kind == "github_user":
        login = item.get("login") or ""
        name = item.get("name") or login or "GitHub user"
        # Reviewer NIT (PR #408 #8): prefer bio for description and
        # leave email solely in attributes.email — email-as-description
        # is odd when bio is the natural one-liner descriptor.
        ent = KnowledgeEntityCreate(
            entity_type="person",
            category="user",
            name=name,
            description=item.get("bio") or None,
            attributes={
                "github_login": login,
                "email": item.get("email"),
                "company": item.get("company"),
                "location": item.get("location"),
                "source": "ap_quickstart_github_cli",
            },
        )
        create_entity(db, ent, tenant_id)
        return "persisted"

    if kind == "github_repo":
        name = item.get("name") or item.get("full_name") or "GitHub repo"
        ent = KnowledgeEntityCreate(
            entity_type="project",
            category="project",
            name=name,
            description=None,
            source_url=item.get("html_url"),
            attributes={
                # Note: the Q3b scanner flattens owner to a login
                # string (`r.get("owner").and_then(|o| o.get("login"))`)
                # before emitting; do NOT read item["owner"]["login"]
                # here — it's already a string at this layer.
                "owner": item.get("owner"),
                "full_name": item.get("full_name"),
                "language": item.get("language"),
                "private": item.get("private"),
                "source": "ap_quickstart_github_cli",
            },
        )
        create_entity(db, ent, tenant_id)
        return "persisted"

    if kind == "github_org":
        ent = KnowledgeEntityCreate(
            entity_type="organization",
            category="organization",
            name=item.get("login") or "GitHub org",
            description=item.get("description"),
            attributes={"source": "ap_quickstart_github_cli"},
        )
        create_entity(db, ent, tenant_id)
        return "persisted"

    if kind in ("github_pr", "github_issue", "quickstart-stub"):
        # PRs / issues are better modelled as observations on the
        # parent repo (PR-Q4-back-2). 'quickstart-stub' lands during
        # stub-wedge runs (Q5 sources before they have real
        # collectors). Returning "recognised" lets the user-visible
        # counter reflect that the workflow saw and understood the
        # item even though nothing landed in the graph.
        return "recognised"

    return "unknown"


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
