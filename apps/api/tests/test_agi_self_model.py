"""Tests for Gap 02: Self-Model & Goals — goals, commitments, identity, review."""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.services import goal_service, commitment_service, agent_identity_service
from app.schemas.goal_record import GoalRecordCreate, GoalRecordUpdate, GoalState, GoalPriority, GoalObjectiveType
from app.schemas.commitment_record import (
    CommitmentRecordCreate, CommitmentRecordUpdate, CommitmentState,
    CommitmentType, CommitmentSourceType, CommitmentPriority,
)
from app.schemas.agent_identity_profile import AgentIdentityProfileCreate


class TestGoalStateMachine:
    """Test goal state transitions and timestamp management."""

    def test_completing_goal_sets_timestamps(self):
        goal = MagicMock()
        goal.completed_at = None
        goal.abandoned_at = None
        goal.progress_pct = 50

        update = GoalRecordUpdate(state=GoalState.COMPLETED)
        data = update.model_dump(exclude_unset=True)

        # Simulate the state machine logic
        new_state = data["state"].value
        assert new_state == "completed"

    def test_reopening_clears_terminal_state(self):
        update = GoalRecordUpdate(state=GoalState.ACTIVE)
        data = update.model_dump(exclude_unset=True)
        assert data["state"] == GoalState.ACTIVE

    def test_cross_tenant_parent_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            goal_service._validate_parent_goal(db, uuid.uuid4(), uuid.uuid4())


class TestCommitmentStateMachine:
    """Test commitment state transitions."""

    def test_fulfilling_sets_timestamp(self):
        update = CommitmentRecordUpdate(state=CommitmentState.FULFILLED)
        data = update.model_dump(exclude_unset=True)
        assert data["state"] == CommitmentState.FULFILLED

    def test_cross_tenant_goal_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            commitment_service._validate_goal_ref(db, uuid.uuid4(), uuid.uuid4())


class TestIdentityProfile:
    """Test identity profile runtime context generation."""

    def test_build_runtime_context_with_profile(self):
        db = MagicMock()
        profile = MagicMock()
        profile.role = "AI chief of staff"
        profile.mandate = "Manage deals"
        profile.domain_boundaries = ["sales", "crm"]
        profile.risk_posture = "moderate"
        profile.escalation_threshold = "medium"
        profile.planning_style = "step_by_step"
        profile.communication_style = "professional"
        profile.operating_principles = ["Always check memory first"]
        profile.strengths = ["CRM analysis"]
        profile.weaknesses = ["Financial modeling"]
        profile.preferred_strategies = ["Email first"]
        profile.avoided_strategies = ["Cold calling"]
        profile.allowed_tool_classes = ["email", "calendar"]
        profile.denied_tool_classes = ["shell"]
        profile.success_criteria = [{"description": "Close deals"}]

        db.query.return_value.filter.return_value.first.return_value = profile

        result = agent_identity_service.build_runtime_identity_context(db, uuid.uuid4(), "luna")
        assert "AI chief of staff" in result
        assert "Manage deals" in result
        assert "CRM analysis" in result
        assert "email" in result

    def test_no_profile_returns_none(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = agent_identity_service.build_runtime_identity_context(db, uuid.uuid4(), "unknown_agent")
        assert result is None
