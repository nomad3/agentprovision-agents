"""Tests for Gap 06: Society of Agents — blackboard, collaboration, coalitions."""

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

from app.services import blackboard_service, collaboration_service, coalition_service
from app.schemas.blackboard import BlackboardCreate, BlackboardEntryCreate, EntryType, AuthorRole
from app.schemas.collaboration import CollaborationSessionCreate, CollaborationPattern, PATTERN_PHASES, PHASE_REQUIRED_ROLES
from app.schemas.coalition import CoalitionTemplateCreate, CoalitionOutcomeCreate


class TestBlackboardAppendOnly:
    """Test blackboard append-only semantics."""

    def test_cross_tenant_plan_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            blackboard_service._validate_plan_ref(db, uuid.uuid4(), uuid.uuid4())

    def test_cross_tenant_goal_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            blackboard_service._validate_goal_ref(db, uuid.uuid4(), uuid.uuid4())

    def test_authority_hierarchy(self):
        assert blackboard_service.AUTHORITY_HIERARCHY["auditor"] > blackboard_service.AUTHORITY_HIERARCHY["synthesizer"]
        assert blackboard_service.AUTHORITY_HIERARCHY["synthesizer"] > blackboard_service.AUTHORITY_HIERARCHY["verifier"]
        assert blackboard_service.AUTHORITY_HIERARCHY["verifier"] > blackboard_service.AUTHORITY_HIERARCHY["critic"]
        assert blackboard_service.AUTHORITY_HIERARCHY["critic"] > blackboard_service.AUTHORITY_HIERARCHY["researcher"]


class TestCollaborationPatterns:
    """Test structured collaboration pattern definitions."""

    def test_all_patterns_have_phases(self):
        for pattern in CollaborationPattern:
            assert pattern.value in PATTERN_PHASES
            assert len(PATTERN_PHASES[pattern.value]) >= 2

    def test_all_phases_have_required_roles(self):
        for pattern, phases in PATTERN_PHASES.items():
            for phase in phases:
                assert phase in PHASE_REQUIRED_ROLES, f"Phase '{phase}' in pattern '{pattern}' has no required roles"

    def test_propose_critique_revise_flow(self):
        phases = PATTERN_PHASES["propose_critique_revise"]
        assert phases == ["propose", "critique", "revise", "verify"]

    def test_role_enforcement_requires_assignments(self):
        """Creating a session without role assignments should fail."""
        db = MagicMock()
        board = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = board

        session_in = CollaborationSessionCreate(
            blackboard_id=uuid.uuid4(),
            pattern=CollaborationPattern.PROPOSE_CRITIQUE_REVISE,
            role_assignments={},  # Empty — should fail
        )
        with pytest.raises(ValueError, match="requires role assignments"):
            collaboration_service.create_session(db, uuid.uuid4(), session_in)

    def test_phase_advance_rejects_agent_not_assigned_to_required_role(self):
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = SimpleNamespace(
            id=session_id,
            tenant_id=tenant_id,
            blackboard_id=uuid.uuid4(),
            pattern="propose_critique_revise",
            status="active",
            current_phase="critique",
            phase_index=1,
            role_assignments={"planner": "luna", "critic": "codex", "verifier": "qwen"},
            rounds_completed=0,
            max_rounds=3,
            updated_at=None,
        )
        db = MagicMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(collaboration_service, "get_session", lambda *_args, **_kwargs: session)
            with pytest.raises(ValueError, match="not assigned to a required role"):
                collaboration_service.advance_phase(
                    db,
                    tenant_id,
                    session_id,
                    agent_slug="luna",
                    contribution="This is critique from the wrong role.",
                )

    def test_terminal_phase_requires_explicit_approval_before_blackboard_write(self):
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = SimpleNamespace(
            id=session_id,
            tenant_id=tenant_id,
            blackboard_id=uuid.uuid4(),
            pattern="propose_critique_revise",
            status="active",
            current_phase="verify",
            phase_index=3,
            role_assignments={"planner": "luna", "critic": "codex", "verifier": "qwen"},
            rounds_completed=0,
            max_rounds=3,
            updated_at=None,
        )
        db = MagicMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(collaboration_service, "get_session", lambda *_args, **_kwargs: session)
            mp.setattr(
                collaboration_service.blackboard_service,
                "add_entry",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not write")),
            )
            with pytest.raises(ValueError, match="must be true or false"):
                collaboration_service.advance_phase(
                    db,
                    tenant_id,
                    session_id,
                    agent_slug="qwen",
                    contribution="Looks good.",
                )

    def test_terminal_completion_stores_last_proposal_not_verifier_note(self):
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        board_id = uuid.uuid4()
        session = SimpleNamespace(
            id=session_id,
            tenant_id=tenant_id,
            blackboard_id=board_id,
            pattern="propose_critique_revise",
            status="active",
            current_phase="verify",
            phase_index=3,
            role_assignments={"planner": "luna", "critic": "codex", "verifier": "qwen"},
            rounds_completed=0,
            max_rounds=3,
            updated_at=None,
            consensus_reached=None,
            outcome=None,
        )
        entry = SimpleNamespace(id=uuid.uuid4(), board_version=4)
        db = MagicMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(collaboration_service, "get_session", lambda *_args, **_kwargs: session)
            mp.setattr(collaboration_service, "_find_last_proposal", lambda *_args, **_kwargs: "Accepted revised plan")
            mp.setattr(
                collaboration_service.blackboard_service,
                "add_entry",
                lambda *_args, **_kwargs: entry,
            )
            result = collaboration_service.advance_phase(
                db,
                tenant_id,
                session_id,
                agent_slug="qwen",
                contribution="Verifier note that should not become outcome",
                agrees_with_previous=True,
            )

        assert result["completed"] is True
        assert result["consensus_reached"] == "yes"
        assert session.status == "completed"
        assert session.consensus_reached == "yes"
        assert session.outcome == "Accepted revised plan"
        assert db.commit.called


class TestCoalitionTemplateValidation:
    """Test coalition template creation validation."""

    def test_invalid_pattern_rejected(self):
        with pytest.raises(ValueError, match="Unknown pattern"):
            coalition_service._validate_pattern_and_roles("nonexistent_pattern", {})

    def test_missing_roles_rejected(self):
        with pytest.raises(ValueError, match="requires roles"):
            coalition_service._validate_pattern_and_roles("propose_critique_revise", {"planner": "luna"})

    def test_valid_template_passes(self):
        coalition_service._validate_pattern_and_roles(
            "propose_critique_revise",
            {"planner": "luna", "critic": "codex", "verifier": "qwen"},
        )

    def test_record_outcome_rejects_role_map_mismatch_with_collaboration(self):
        tenant_id = uuid.uuid4()
        collab_id = uuid.uuid4()
        collab = SimpleNamespace(
            id=collab_id,
            tenant_id=tenant_id,
            pattern="propose_critique_revise",
            role_assignments={"planner": "luna", "critic": "codex", "verifier": "qwen"},
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = collab

        with pytest.raises(ValueError, match="does not match collaboration"):
            coalition_service.record_outcome(
                db,
                tenant_id,
                CoalitionOutcomeCreate(
                    collaboration_id=collab_id,
                    task_type="code",
                    pattern="propose_critique_revise",
                    role_agent_map={"planner": "luna", "critic": "other", "verifier": "qwen"},
                    success="yes",
                    quality_score=0.9,
                    rounds_completed=2,
                    cost_usd=0.1,
                ),
            )

    def test_recommend_coalition_uses_task_type_specific_stats_not_global_template_scores(self):
        tenant_id = uuid.uuid4()
        template_a = SimpleNamespace(
            id=uuid.uuid4(),
            name="Code Team A",
            pattern="propose_critique_revise",
            role_agent_map={"planner": "luna", "critic": "codex", "verifier": "qwen"},
            task_types=["code"],
            status="active",
            avg_quality_score=0.2,
        )
        template_b = SimpleNamespace(
            id=uuid.uuid4(),
            name="Code Team B",
            pattern="propose_critique_revise",
            role_agent_map={"planner": "luna", "critic": "claude", "verifier": "qwen"},
            task_types=["code"],
            status="active",
            avg_quality_score=0.95,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [template_a, template_b]

        def _stats(_db, _tenant_id, template_id, task_type):
            assert task_type == "code"
            if template_id == template_a.id:
                return {"total": 3, "success_count": 3, "avg_quality": 0.8, "avg_cost": 0.2, "avg_rounds": 1.0}
            return {"total": 3, "success_count": 1, "avg_quality": 0.4, "avg_cost": 0.4, "avg_rounds": 3.0}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(coalition_service, "_compute_task_type_stats", _stats)
            result = coalition_service.recommend_coalition(db, tenant_id, "code", min_uses=2)

        assert len(result) == 2
        assert result[0]["name"] == "Code Team A"
        assert "task_type=code" in result[0]["reasoning"]
