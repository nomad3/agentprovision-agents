"""Smoke test for the api-side shadow wiring at cli_session_manager.

The full ``run_agent_session`` is huge — these tests pin the wrapper's
contract (read flags, call legacy, fire shadow, never poison) without
exercising the full session body. We patch
``_run_agent_session_legacy`` to return a synthetic (response_text,
metadata) and verify ``maybe_run_shadow`` runs correctly.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import cli_session_manager
from app.services.cli_orchestrator_shadow import maybe_run_shadow


@pytest.fixture
def fake_db():
    return MagicMock()


def test_run_agent_session_calls_legacy_then_shadow(fake_db):
    """Public run_agent_session calls the legacy impl AND fires shadow."""
    legacy_return = ("hello", {"platform": "claude_code"})
    with patch.object(
        cli_session_manager,
        "_run_agent_session_legacy",
        return_value=legacy_return,
    ) as legacy_mock, patch(
        "app.services.cli_orchestrator_shadow.maybe_run_shadow"
    ) as shadow_mock:
        result = cli_session_manager.run_agent_session(
            db=fake_db,
            tenant_id="tenant-1",
            user_id="user-1",
            platform="claude_code",
            agent_slug="luna",
            message="hi",
            channel="chat",
            sender_phone=None,
            conversation_summary="",
        )

    assert result == legacy_return
    legacy_mock.assert_called_once()
    shadow_mock.assert_called_once()
    # The shadow call gets the legacy outcome.
    kwargs = shadow_mock.call_args.kwargs
    assert kwargs["response_text"] == "hello"
    assert kwargs["metadata"] == {"platform": "claude_code"}
    assert kwargs["platform"] == "claude_code"


def test_run_agent_session_swallows_shadow_exception(fake_db):
    """Shadow raising never poisons the response."""
    legacy_return = ("hello", {"platform": "claude_code"})
    with patch.object(
        cli_session_manager,
        "_run_agent_session_legacy",
        return_value=legacy_return,
    ), patch(
        "app.services.cli_orchestrator_shadow.maybe_run_shadow",
        side_effect=RuntimeError("shadow exploded"),
    ):
        result = cli_session_manager.run_agent_session(
            db=fake_db,
            tenant_id="tenant-1",
            user_id="user-1",
            platform="claude_code",
            agent_slug="luna",
            message="hi",
            channel="chat",
            sender_phone=None,
            conversation_summary="",
        )
    # Response must still be returned.
    assert result == legacy_return


def test_maybe_run_shadow_with_no_tenant_features_row_does_nothing(fake_db):
    """If tenant_features lookup returns nothing, default flags are
    (False, False) — shadow runs against a stub but doesn't poison.

    More importantly: the shadow path returns silently regardless.
    """
    fake_db.query.return_value.filter.return_value.first.return_value = None
    # Should not raise even with no tenant_features row.
    maybe_run_shadow(
        db=fake_db,
        tenant_id="tenant-1",
        platform="claude_code",
        response_text="hi",
        metadata={"platform": "claude_code"},
    )


def test_maybe_run_shadow_with_use_resilient_skips(fake_db):
    """When use_resilient_executor is TRUE, the api-side shadow is not
    needed (the resilient path IS the path). Helper returns silently.
    """
    fake_row = MagicMock()
    fake_row.use_resilient_executor = True
    fake_row.shadow_mode_real_dispatch = False
    fake_db.query.return_value.filter.return_value.first.return_value = fake_row
    # Patch run_shadow_comparison to assert it's NOT called.
    with patch(
        "app.services.cli_orchestrator_shadow.run_shadow_comparison"
    ) as run_mock:
        maybe_run_shadow(
            db=fake_db,
            tenant_id="tenant-1",
            platform="claude_code",
            response_text="hi",
            metadata={"platform": "claude_code"},
        )
    run_mock.assert_not_called()


def test_maybe_run_shadow_flag_off_runs_stub_replay(fake_db):
    """With flags (False, False) — default — shadow runs against the
    stubbed _ReplayAdapter (no real Temporal dispatch)."""
    fake_row = MagicMock()
    fake_row.use_resilient_executor = False
    fake_row.shadow_mode_real_dispatch = False
    fake_db.query.return_value.filter.return_value.first.return_value = fake_row
    with patch(
        "app.services.cli_orchestrator_shadow.run_shadow_comparison"
    ) as run_mock:
        maybe_run_shadow(
            db=fake_db,
            tenant_id="tenant-1",
            platform="claude_code",
            response_text="hi",
            metadata={"platform": "claude_code"},
        )
    run_mock.assert_called_once()
    # The third positional arg is the executor — confirm it's a
    # ResilientExecutor instance (not a Temporal-dispatching one).
    _, _, executor = run_mock.call_args.args
    # The stubbed adapter is the only one registered.
    adapter_names = list(executor._adapters.keys())
    assert "claude_code" in adapter_names
