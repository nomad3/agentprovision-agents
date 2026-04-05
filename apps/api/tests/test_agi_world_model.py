"""Tests for Gap 01: World Model — assertions, snapshots, disputes, causal edges."""

import os
import sys
import pytest
import uuid
from datetime import datetime, timedelta
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

from app.services import world_state_service, causal_edge_service
from app.schemas.world_state import WorldStateAssertionCreate, AssertionSourceType
from app.schemas.causal_edge import CausalEdgeCreate, CauseType, EffectType


class TestAssertionLifecycle:
    """Test assertion create/corroborate/supersede/dispute."""

    def test_cross_tenant_entity_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            world_state_service._validate_entity_ref(db, uuid.uuid4(), uuid.uuid4())

    def test_cross_tenant_observation_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            world_state_service._validate_observation_ref(db, uuid.uuid4(), uuid.uuid4())

    def test_assert_state_conflicting_source_marks_both_sides_disputed(self):
        existing = SimpleNamespace(
            value_json={"stage": "proposal"},
            source_type="observation",
            status="active",
            dispute_reason=None,
            valid_to=None,
            superseded_by_id=None,
        )
        existing_query = MagicMock()
        existing_query.filter.return_value.first.return_value = existing
        db = MagicMock()
        db.query.return_value = existing_query

        assertion_in = WorldStateAssertionCreate(
            subject_slug="lead:acme",
            attribute_path="stage",
            value_json={"stage": "negotiation"},
            confidence=0.8,
            source_type=AssertionSourceType.AGENT,
            freshness_ttl_hours=24,
            subject_entity_id=None,
            source_observation_id=None,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(world_state_service, "_expire_stale_assertions", lambda *_args, **_kwargs: [])
            updated = []
            mp.setattr(
                world_state_service,
                "_update_snapshot_no_expire",
                lambda *args, **kwargs: updated.append((args, kwargs)),
            )
            assertion = world_state_service.assert_state(
                db,
                tenant_id=uuid.uuid4(),
                assertion_in=assertion_in,
            )

        assert existing.status == "disputed"
        assert assertion.status == "disputed"
        assert existing.dispute_reason is not None
        assert assertion.dispute_reason is not None
        assert db.add.called
        assert db.commit.called
        assert updated, "snapshot should be refreshed"

    def test_resolve_dispute_active_supersedes_other_active_claim(self):
        tenant_id = uuid.uuid4()
        assertion_id = uuid.uuid4()
        disputed = SimpleNamespace(
            id=assertion_id,
            tenant_id=tenant_id,
            subject_slug="lead:acme",
            subject_entity_id=None,
            attribute_path="stage",
            status="disputed",
            dispute_reason="conflict",
            valid_to=datetime.utcnow(),
            updated_at=None,
        )
        db = MagicMock()
        update_query = MagicMock()
        update_query.filter.return_value.update.return_value = 1
        snapshot_updates = []

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(world_state_service, "get_assertion", lambda *_args, **_kwargs: disputed)
            mp.setattr(
                world_state_service,
                "_update_snapshot_no_expire",
                lambda *args, **kwargs: snapshot_updates.append((args, kwargs)),
            )
            db.query.return_value = update_query
            result = world_state_service.resolve_dispute(
                db,
                tenant_id=tenant_id,
                assertion_id=assertion_id,
                resolution="active",
            )

        assert result is disputed
        assert disputed.status == "active"
        assert disputed.dispute_reason is None
        assert disputed.valid_to is None
        update_query.filter.return_value.update.assert_called_once()
        assert snapshot_updates
        assert db.commit.called


class TestConfidenceDecay:
    """Test time-based confidence decay."""

    def test_no_decay_before_half_ttl(self):
        assertion = MagicMock()
        assertion.confidence = 0.8
        assertion.valid_from = datetime.utcnow() - timedelta(hours=10)
        assertion.freshness_ttl_hours = 168  # 7 days
        result = world_state_service._compute_decayed_confidence(assertion)
        assert result == 0.8  # No decay before 84h

    def test_decay_after_half_ttl(self):
        assertion = MagicMock()
        assertion.confidence = 0.8
        assertion.valid_from = datetime.utcnow() - timedelta(hours=126)  # 75% of 168h
        assertion.freshness_ttl_hours = 168
        result = world_state_service._compute_decayed_confidence(assertion)
        assert result < 0.8
        assert result > 0.0

    def test_full_decay_near_ttl(self):
        assertion = MagicMock()
        assertion.confidence = 0.8
        assertion.valid_from = datetime.utcnow() - timedelta(hours=165)  # ~98% of TTL
        assertion.freshness_ttl_hours = 168
        result = world_state_service._compute_decayed_confidence(assertion)
        assert result < 0.5


class TestWorldStateContext:
    """Test runtime context generation."""

    def test_context_includes_freshness_label(self):
        db = MagicMock()
        snapshot = MagicMock()
        snapshot.projected_state = {"stage": "proposal"}
        snapshot.disputed_attributes = []
        snapshot.unstable_attributes = []
        snapshot.avg_confidence = 0.85
        snapshot.min_confidence = 0.75
        db.query.return_value.filter.return_value.first.return_value = snapshot

        result = world_state_service.build_world_state_context(db, uuid.uuid4(), ["lead:acme"])
        assert "fresh" in result
        assert "proposal" in result

    def test_context_shows_disputes(self):
        db = MagicMock()
        snapshot = MagicMock()
        snapshot.projected_state = {"stage": "proposal"}
        snapshot.disputed_attributes = ["contact"]
        snapshot.unstable_attributes = []
        snapshot.avg_confidence = 0.7
        snapshot.min_confidence = 0.5
        db.query.return_value.filter.return_value.first.return_value = snapshot

        result = world_state_service.build_world_state_context(db, uuid.uuid4(), ["lead:acme"])
        assert "DISPUTED" in result
        assert "contact" in result

    def test_empty_slugs_returns_empty(self):
        db = MagicMock()
        result = world_state_service.build_world_state_context(db, uuid.uuid4(), [])
        assert result == ""


class TestCausalEdge:
    """Test causal edge creation and validation."""

    def test_cross_tenant_assertion_validation(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with pytest.raises(ValueError, match="not found in this tenant"):
            causal_edge_service._validate_assertion_ref(db, uuid.uuid4(), uuid.uuid4())

    def test_existing_edge_corroborates_to_confirmed(self):
        existing = SimpleNamespace(
            observation_count=9,
            confidence=0.75,
            status="corroborated",
            updated_at=None,
            mechanism=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        edge_in = CausalEdgeCreate(
            cause_type=CauseType.AGENT_ACTION,
            cause_summary="send pricing email",
            cause_ref={"action": "send_email"},
            effect_type=EffectType.GOAL_PROGRESS,
            effect_summary="deal advanced",
            effect_ref={"stage": "proposal"},
            confidence=0.8,
            mechanism="timely follow-up",
            source_assertion_id=None,
            agent_slug="luna",
        )

        result = causal_edge_service.record_causal_edge(
            db,
            tenant_id=uuid.uuid4(),
            edge_in=edge_in,
        )

        assert result is existing
        assert existing.observation_count == 10
        assert existing.status == "confirmed"
        assert existing.confidence > 0.75
        assert existing.mechanism == "timely follow-up"
        assert db.commit.called
