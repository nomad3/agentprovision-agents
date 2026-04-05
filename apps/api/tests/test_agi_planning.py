"""Tests for Gap 03: Long-Horizon Planning — plans, steps, replanning, budgets."""

from datetime import datetime
import os
import pytest
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.types import UserDefinedType

os.environ["TESTING"] = "True"
sys.path.append(str(Path(__file__).resolve().parents[1]))

if "pgvector.sqlalchemy" not in sys.modules:
    pgvector_module = ModuleType("pgvector")
    pgvector_sqlalchemy = ModuleType("pgvector.sqlalchemy")

    class _FakeVector(UserDefinedType):
        def __init__(self, *args, **kwargs):
            pass

        def get_col_spec(self, **kw):
            return "VECTOR"

    pgvector_sqlalchemy.Vector = _FakeVector
    pgvector_module.sqlalchemy = pgvector_sqlalchemy
    sys.modules["pgvector"] = pgvector_module
    sys.modules["pgvector.sqlalchemy"] = pgvector_sqlalchemy

from app.services import plan_service
from app.schemas.plan import PlanCreate, PlanUpdate, PlanStatus, PlanStepCreate


class TestFailureClassification:
    """Test the failure classifier."""

    def test_timeout_is_transient(self):
        assert plan_service.classify_failure("Connection timeout after 30s") == "transient"

    def test_rate_limit_is_transient(self):
        assert plan_service.classify_failure("rate limit reached") == "transient"

    def test_not_found_is_missing_info(self):
        assert plan_service.classify_failure("Entity not found in knowledge graph") == "missing_info"

    def test_assumption_invalid(self):
        assert plan_service.classify_failure("Assumption invalidated: budget no longer approved") == "invalid_assumption"

    def test_approval_required(self):
        assert plan_service.classify_failure("Action requires approval from admin") == "blocked_approval"

    def test_state_changed(self):
        assert plan_service.classify_failure("Deal stage changed since plan was created") == "world_state_change"

    def test_unknown_defaults_to_transient(self):
        assert plan_service.classify_failure("Something weird happened") == "transient"


class TestRepairPolicies:
    """Test repair action mapping."""

    def test_transient_retries(self):
        assert plan_service.get_repair_action("transient") == "retry"

    def test_missing_info_gathers(self):
        assert plan_service.get_repair_action("missing_info") == "gather_info"

    def test_invalid_assumption_replans(self):
        assert plan_service.get_repair_action("invalid_assumption") == "replan"

    def test_blocked_escalates(self):
        assert plan_service.get_repair_action("blocked_approval") == "escalate"

    def test_world_change_replans(self):
        assert plan_service.get_repair_action("world_state_change") == "replan"


class TestBudgetChecking:
    """Test budget enforcement logic."""

    def test_budget_ok_when_no_limits(self):
        db = MagicMock()
        plan = MagicMock()
        plan.budget_max_actions = None
        plan.budget_max_cost_usd = None
        plan.budget_max_runtime_hours = None
        plan.budget_actions_used = 5
        plan.budget_cost_used = 1.0
        plan.created_at = MagicMock()
        plan.tenant_id = uuid.uuid4()
        plan.id = uuid.uuid4()

        db.query.return_value.filter.return_value.first.return_value = plan
        result = plan_service.check_budget(db, plan.tenant_id, plan.id)
        assert result["budget_ok"] is True
        assert len(result["violations"]) == 0

    def test_actions_budget_violation(self):
        db = MagicMock()
        plan = MagicMock()
        plan.budget_max_actions = 5
        plan.budget_actions_used = 5
        plan.budget_max_cost_usd = None
        plan.budget_max_runtime_hours = None
        plan.budget_cost_used = 0
        plan.created_at = MagicMock()
        plan.tenant_id = uuid.uuid4()
        plan.id = uuid.uuid4()

        db.query.return_value.filter.return_value.first.return_value = plan
        result = plan_service.check_budget(db, plan.tenant_id, plan.id)
        assert result["budget_ok"] is False
        assert any(v["budget"] == "actions" for v in result["violations"])

    def test_cross_tenant_goal_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            plan_service._validate_goal_ref(db, uuid.uuid4(), uuid.uuid4())


class TestPlanExecutionLifecycle:
    """Test execution start, fallback, resume, and budget gates."""

    def test_update_plan_starts_first_step_when_execution_begins(self):
        tenant_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan = SimpleNamespace(
            id=plan_id,
            tenant_id=tenant_id,
            status="approved",
            owner_agent_slug="luna",
            current_step_index=0,
            updated_at=None,
        )
        first_step = SimpleNamespace(
            id=uuid.uuid4(),
            status="pending",
            started_at=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = first_step
        events = []

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(plan_service, "get_plan", lambda *_args, **_kwargs: plan)
            mp.setattr(plan_service, "_enforce_budget_before_step", lambda *_args, **_kwargs: None)
            mp.setattr(plan_service, "_log_event", lambda *args, **kwargs: events.append((args, kwargs)))
            result = plan_service.update_plan(
                db,
                tenant_id,
                plan_id,
                PlanUpdate(status=PlanStatus.EXECUTING),
            )

        assert result is plan
        assert plan.status == "executing"
        assert first_step.status == "running"
        assert first_step.started_at is not None
        assert any(call[0][2] == "step_started" for call in events)
        assert db.commit.called

    def test_advance_step_pauses_on_last_step_budget_violation(self):
        tenant_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan = SimpleNamespace(
            id=plan_id,
            tenant_id=tenant_id,
            status="executing",
            current_step_index=0,
            budget_actions_used=0,
            updated_at=None,
        )
        current_step = SimpleNamespace(
            id=uuid.uuid4(),
            status="running",
            completed_at=None,
            output=None,
        )
        db = MagicMock()
        filter_result = MagicMock()
        filter_result.first.side_effect = [current_step, None]
        db.query.return_value.filter.return_value = filter_result

        def _budget_pause(_db, current_plan, _plan_id):
            current_plan.status = "paused"
            return {"violations": [{"budget": "actions"}]}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(plan_service, "get_plan", lambda *_args, **_kwargs: plan)
            mp.setattr(plan_service, "_enforce_budget_before_step", _budget_pause)
            mp.setattr(plan_service, "_log_event", lambda *args, **kwargs: None)
            result = plan_service.advance_step(
                db,
                tenant_id,
                plan_id,
                step_output={"ok": True},
            )

        assert result is current_step
        assert current_step.status == "completed"
        assert plan.status == "paused"
        assert db.commit.called

    def test_apply_fallback_resets_stale_target_step_state(self):
        plan = SimpleNamespace(
            id=uuid.uuid4(),
            current_step_index=1,
            status="executing",
        )
        failed_step = SimpleNamespace(
            id=uuid.uuid4(),
            step_index=1,
            fallback_step_index=3,
        )
        fallback = SimpleNamespace(
            id=uuid.uuid4(),
            step_index=3,
            title="retry later",
            status="failed",
            started_at=None,
            completed_at=datetime.utcnow(),
            error="old failure",
            output={"stale": True},
            retry_policy={"max_attempts": 3, "_attempts": 3},
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = fallback

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(plan_service, "_log_event", lambda *args, **kwargs: None)
            result = plan_service._apply_fallback(
                db,
                plan,
                failed_step,
                error="timeout",
                failure_class="transient",
            )

        assert result["fallback_step_index"] == 3
        assert plan.current_step_index == 3
        assert fallback.status == "running"
        assert fallback.error is None
        assert fallback.output is None
        assert fallback.completed_at is None
        assert "_attempts" not in fallback.retry_policy

    def test_resume_plan_uses_current_step_index_after_fallback(self):
        tenant_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan = SimpleNamespace(
            id=plan_id,
            tenant_id=tenant_id,
            status="paused",
            current_step_index=3,
            updated_at=None,
        )
        resume_step = SimpleNamespace(
            id=uuid.uuid4(),
            step_index=3,
            title="fallback step",
            status="failed",
            started_at=None,
            error="old error",
            output={"stale": True},
            retry_policy={"max_attempts": 3, "_attempts": 2},
            completed_at=datetime.utcnow(),
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = resume_step
        events = []

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(plan_service, "get_plan", lambda *_args, **_kwargs: plan)
            mp.setattr(
                plan_service,
                "check_budget",
                lambda *_args, **_kwargs: {"violations": [], "warnings": []},
            )
            mp.setattr(plan_service, "_log_event", lambda *args, **kwargs: events.append((args, kwargs)))
            result = plan_service.resume_plan(db, tenant_id, plan_id)

        assert result["resumed_from_step"] == 3
        assert plan.status == "executing"
        assert plan.current_step_index == 3
        assert resume_step.status == "running"
        assert resume_step.error is None
        assert resume_step.output is None
        assert resume_step.completed_at is None
        assert "_attempts" not in resume_step.retry_policy
        assert any(call[0][2] == "resumed" for call in events)
        assert db.commit.called

    def test_resume_plan_rejects_over_budget_restart(self):
        tenant_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan = SimpleNamespace(
            id=plan_id,
            tenant_id=tenant_id,
            status="paused",
            current_step_index=1,
            updated_at=None,
        )
        resume_step = SimpleNamespace(
            id=uuid.uuid4(),
            step_index=1,
            title="draft email",
            status="failed",
            started_at=None,
            error="needs retry",
            output=None,
            retry_policy={"max_attempts": 3, "_attempts": 1},
            completed_at=datetime.utcnow(),
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = resume_step

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(plan_service, "get_plan", lambda *_args, **_kwargs: plan)
            mp.setattr(
                plan_service,
                "check_budget",
                lambda *_args, **_kwargs: {
                    "violations": [{"message": "Action budget exhausted (5/5)"}],
                    "warnings": [],
                },
            )
            result = plan_service.resume_plan(db, tenant_id, plan_id)

        assert result["error"] == "budget_exceeded"
        assert "Cannot resume" in result["message"]
        assert plan.status == "paused"
        assert resume_step.status == "failed"
        assert not db.commit.called
