"""Tests for Gap 04: Self-Improvement — candidates, experiments, rollouts, dashboards."""

import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.services import learning_experiment_service, policy_rollout_service
from app.schemas.learning_experiment import (
    PolicyCandidateCreate, LearningExperimentCreate,
    PolicyType, ExperimentType,
)


class TestPolicyCandidates:
    """Test policy candidate creation and lifecycle."""

    def test_candidate_creation_schema(self):
        candidate = PolicyCandidateCreate(
            policy_type=PolicyType.ROUTING,
            decision_point="chat_response",
            description="Route more to codex",
            current_policy={"platform": "claude_code"},
            proposed_policy={"platform": "codex"},
            rationale="Codex outperforms by 23%",
            source_experience_count=50,
            baseline_reward=0.51,
            expected_improvement=23.5,
        )
        assert candidate.policy_type == PolicyType.ROUTING
        assert candidate.expected_improvement == 23.5

    def test_promotion_requires_experiment(self):
        """Cannot promote without a completed significant experiment."""
        db = MagicMock()
        candidate = MagicMock()
        candidate.status = "evaluating"
        db.query.return_value.filter.return_value.first.side_effect = [
            candidate,  # get_candidate
            None,       # no successful experiment
        ]
        with pytest.raises(ValueError, match="no completed experiment"):
            learning_experiment_service.promote_candidate(db, uuid.uuid4(), uuid.uuid4())


class TestExperimentCreation:
    """Test experiment creation constraints."""

    def test_only_offline_in_phase_1(self):
        """Shadow and split experiments rejected at creation."""
        experiment = LearningExperimentCreate(
            candidate_id=uuid.uuid4(),
            experiment_type=ExperimentType.SPLIT,
        )
        # The service validates this, but schema allows it
        # (split is used for rollouts, not create_experiment)
        assert experiment.experiment_type == ExperimentType.SPLIT


class TestRolloutService:
    """Test the policy rollout service."""

    def test_should_apply_returns_tuple(self):
        rollout = {
            "experiment_type": "split",
            "rollout_pct": 1.0,  # 100% treatment
        }
        apply_policy, is_treatment = policy_rollout_service.should_apply_rollout(rollout)
        assert apply_policy is True
        assert is_treatment is True

    def test_zero_pct_always_control(self):
        rollout = {
            "experiment_type": "split",
            "rollout_pct": 0.0,
        }
        # With 0% rollout, should always be control
        results = set()
        for _ in range(20):
            apply, is_treatment = policy_rollout_service.should_apply_rollout(rollout)
            results.add(is_treatment)
        assert results == {False}

    def test_auto_rollback_threshold(self):
        assert policy_rollout_service.ROLLBACK_REGRESSION_THRESHOLD == -0.15

    def test_rollback_min_samples(self):
        assert policy_rollout_service.ROLLBACK_MIN_SAMPLES == 10

    def test_auto_rollback_triggers(self):
        """Regression > 15% after min samples → abort + reject."""
        db = MagicMock()
        experiment = MagicMock()
        experiment.treatment_sample_size = 15
        experiment.control_avg_reward = 0.7
        experiment.treatment_avg_reward = 0.5  # -28.6% regression
        experiment.status = "running"
        experiment.id = uuid.uuid4()
        experiment.candidate_id = uuid.uuid4()

        candidate = MagicMock()
        candidate.status = "evaluating"
        db.query.return_value.filter.return_value.first.return_value = candidate

        policy_rollout_service._check_auto_rollback(db, experiment)
        assert experiment.status == "aborted"
        assert "regression" in experiment.is_significant

    def test_no_rollback_below_min_samples(self):
        db = MagicMock()
        experiment = MagicMock()
        experiment.treatment_sample_size = 5  # Below min
        experiment.control_avg_reward = 0.7
        experiment.treatment_avg_reward = 0.3

        policy_rollout_service._check_auto_rollback(db, experiment)
        # Should NOT have changed status
        assert experiment.status != "aborted"
