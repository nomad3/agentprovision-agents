"""Regression cover for the TIMESTAMPTZ migration on workflow_runs.

Migration 132 converted `workflow_runs.started_at` / `completed_at`
from naive TIMESTAMP to TIMESTAMPTZ. The follow-up commits in the same
PR removed the `_utc_aware()` shim + `now_naive` workaround that were
bridging the gap. These tests lock in the model-level contract so a
future refactor doesn't silently revert to naive columns and re-break
the CLI deserialisation path.
"""

from app.models.dynamic_workflow import WorkflowRun


def test_started_at_column_is_tz_aware():
    # The Column type itself must carry timezone=True so SQLAlchemy
    # emits TIMESTAMPTZ DDL and Pydantic v2 serialisers see a tz-aware
    # type at introspection time.
    col = WorkflowRun.__table__.columns["started_at"]
    assert col.type.timezone is True, (
        "WorkflowRun.started_at must be TIMESTAMPTZ "
        "(migration 132). Naive serialisation breaks the CLI."
    )


def test_completed_at_column_is_tz_aware():
    col = WorkflowRun.__table__.columns["completed_at"]
    assert col.type.timezone is True, (
        "WorkflowRun.completed_at must be TIMESTAMPTZ (migration 132)."
    )


def test_started_at_default_is_tz_aware():
    # The default callable must produce tz-aware datetimes so the value
    # round-trips identically through Pydantic without the `_utc_aware`
    # shim we removed. A naive default would break the cli wire path
    # again at the first insert.
    col = WorkflowRun.__table__.columns["started_at"]
    assert col.default is not None
    produced = col.default.arg(None)  # call_for_default takes a ctx
    assert produced.tzinfo is not None, (
        "WorkflowRun.started_at default must produce tz-aware UTC datetimes; "
        f"got {produced!r}"
    )
