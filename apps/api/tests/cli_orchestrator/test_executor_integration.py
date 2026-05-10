"""End-to-end executor integration test for the chat hot path.

Exercises ``agent_router._resilient_chain_walk`` with a mocked
``TemporalActivityAdapter`` (so no real Temporal dispatch happens) and
asserts the resulting metadata's ``routing_summary`` carries the same
keys the legacy path produces (``served_by``, ``requested``, ``chain``,
``fallback_fired``) — the chat UI footer reads from those keys
directly, so a divergence here is a customer-visible regression.

Also asserts ExecutionResult.to_metadata_dict() produces the public
contract keys (status, platform, platform_attempted, attempt_count,
actionable_hint, workflow_id, activity_id, exit_code, error,
stdout_summary, stderr_summary).
"""
from __future__ import annotations

from unittest.mock import patch

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.executor import ResilientExecutor
from cli_orchestrator.status import Status

from app.services.agent_router import _resilient_chain_walk


# --------------------------------------------------------------------------
# ExecutionResult.to_metadata_dict shape gate
# --------------------------------------------------------------------------

def test_to_metadata_dict_has_all_public_contract_keys():
    """to_metadata_dict() is read by the chat UI footer — pin the keys."""
    result = ExecutionResult(
        status=Status.EXECUTION_SUCCEEDED,
        platform="claude_code",
        response_text="hi",
        stdout_summary="raw",
        stderr_summary="",
        exit_code=0,
        platform_attempted=["claude_code"],
        attempt_count=1,
        actionable_hint=None,
        workflow_id="wf-1",
        activity_id=None,
        metadata={"tokens_in": 10, "tokens_out": 20},
    )
    meta = result.to_metadata_dict()
    expected_keys = {
        "status", "platform", "platform_attempted", "attempt_count",
        "actionable_hint", "workflow_id", "activity_id", "exit_code",
        "error", "stdout_summary", "stderr_summary",
    }
    assert expected_keys.issubset(meta.keys()), (
        f"Missing keys: {expected_keys - set(meta.keys())}"
    )
    # Adapter passthrough metadata is merged.
    assert meta.get("tokens_in") == 10
    assert meta.get("tokens_out") == 20
    # Status renders as the canonical lowercase wire string.
    assert meta["status"] == "execution_succeeded"


# --------------------------------------------------------------------------
# Full flag-ON chain walk via _resilient_chain_walk
# --------------------------------------------------------------------------

class _MockTemporalAdapter:
    """Drop-in replacement for TemporalActivityAdapter — no SDK calls."""

    def __init__(self, platform: str, *, status: Status, response_text: str = ""):
        self.name = platform
        self._platform = platform
        self._status = status
        self._response_text = response_text

    def preflight(self, req):
        return PreflightResult.succeed()

    def run(self, req):
        if self._status is Status.EXECUTION_SUCCEEDED:
            return ExecutionResult(
                status=self._status,
                platform=self._platform,
                response_text=self._response_text or "ok",
                exit_code=0,
                attempt_count=1,
                metadata={"input_tokens": 5, "output_tokens": 10},
            )
        return ExecutionResult(
            status=self._status,
            platform=self._platform,
            error_message=f"{self._platform} returned {self._status.value}",
            attempt_count=1,
        )

    def classify_error(self, stderr, exit_code, exc):
        from cli_orchestrator.classifier import classify
        return classify(stderr, exit_code, exc)


def test_resilient_chain_walk_success_emits_routing_summary_with_legacy_keys():
    """Happy path: the new chain walk surfaces the same routing_summary
    keys the chat UI footer reads from the legacy path."""

    def _fake_adapter_factory(*, platform, **_):
        return _MockTemporalAdapter(
            platform=platform,
            status=Status.EXECUTION_SUCCEEDED,
            response_text="hello world",
        )

    with patch(
        "cli_orchestrator.adapters.temporal_activity.TemporalActivityAdapter",
        side_effect=_fake_adapter_factory,
    ):
        response_text, metadata = _resilient_chain_walk(
            db=None,
            tenant_id="tenant-1",
            user_id="user-1",
            platform="claude_code",
            cli_chain=["claude_code"],
            agent_slug="luna",
            agent_skill_slugs=None,
            message="hi",
            channel="chat",
            sender_phone=None,
            conversation_summary="",
            image_b64="",
            image_mime="",
            db_session_memory=None,
            pre_built_memory_context=None,
            agent_tier="full",
            agent_tool_groups=None,
            agent_memory_domains=None,
        )

    assert response_text == "hello world"
    assert "routing_summary" in metadata
    rs = metadata["routing_summary"]
    # Legacy footer reads display labels — _build_routing_summary
    # translates internal slugs to human-readable strings, and ALSO
    # surfaces the snake_case id under served_by_platform.
    assert rs.get("served_by") == "Claude Code"
    assert rs.get("served_by_platform") == "claude_code"
    # No fallback fired (served == requested) → ``requested`` key is
    # intentionally omitted by _build_routing_summary in that case.
    assert "requested" not in rs
    assert rs.get("chain_length") == 1
    # Phase 2 ExecutionResult metadata also lands.
    assert metadata.get("status") == "execution_succeeded"
    assert metadata.get("platform_attempted") == ["claude_code"]
    assert metadata.get("attempt_count") >= 1


def test_resilient_chain_walk_quota_falls_through_to_next_platform():
    """Quota on first platform → executor falls through to next →
    metadata.routing_summary.served_by reflects the platform that
    actually served, served_by != requested → fallback_fired true."""

    call_order = []

    def _fake_adapter_factory(*, platform, **_):
        call_order.append(platform)
        if platform == "claude_code":
            return _MockTemporalAdapter(platform=platform, status=Status.QUOTA_EXHAUSTED)
        return _MockTemporalAdapter(
            platform=platform,
            status=Status.EXECUTION_SUCCEEDED,
            response_text="codex served",
        )

    with patch(
        "cli_orchestrator.adapters.temporal_activity.TemporalActivityAdapter",
        side_effect=_fake_adapter_factory,
    ):
        response_text, metadata = _resilient_chain_walk(
            db=None,
            tenant_id="tenant-1",
            user_id="user-1",
            platform="claude_code",
            cli_chain=["claude_code", "codex"],
            agent_slug="luna",
            agent_skill_slugs=None,
            message="hi",
            channel="chat",
            sender_phone=None,
            conversation_summary="",
            image_b64="",
            image_mime="",
            db_session_memory=None,
            pre_built_memory_context=None,
            agent_tier="full",
            agent_tool_groups=None,
            agent_memory_domains=None,
        )

    assert response_text == "codex served"
    rs = metadata["routing_summary"]
    assert rs.get("served_by") == "Codex CLI"
    assert rs.get("served_by_platform") == "codex"
    # Fallback fired → requested + requested_platform present.
    assert rs.get("requested") == "Claude Code"
    assert rs.get("requested_platform") == "claude_code"
    # platform_attempted reflects the chain walk.
    assert metadata.get("platform_attempted") == ["claude_code", "codex"]


def test_resilient_chain_walk_exhausted_chain_marks_routing_error_state():
    """All platforms fail → response_text=None, routing_summary
    error_state='exhausted' so the failure UX has CLI attribution."""

    def _fake_adapter_factory(*, platform, **_):
        return _MockTemporalAdapter(platform=platform, status=Status.QUOTA_EXHAUSTED)

    with patch(
        "cli_orchestrator.adapters.temporal_activity.TemporalActivityAdapter",
        side_effect=_fake_adapter_factory,
    ):
        response_text, metadata = _resilient_chain_walk(
            db=None,
            tenant_id="tenant-1",
            user_id="user-1",
            platform="claude_code",
            cli_chain=["claude_code", "codex"],
            agent_slug="luna",
            agent_skill_slugs=None,
            message="hi",
            channel="chat",
            sender_phone=None,
            conversation_summary="",
            image_b64="",
            image_mime="",
            db_session_memory=None,
            pre_built_memory_context=None,
            agent_tier="full",
            agent_tool_groups=None,
            agent_memory_domains=None,
        )

    assert response_text is None
    rs = metadata["routing_summary"]
    assert rs.get("error_state") == "exhausted"
    # served_by_platform is None on exhausted chain; served_by is the
    # legacy "—" placeholder.
    assert rs.get("served_by_platform") is None
    # `requested` (display label) IS set on exhausted chain so the UI
    # can render "Tried X, Y — all failed".
    assert rs.get("requested") == "Claude Code"
    assert rs.get("requested_platform") == "claude_code"
    assert "error" in metadata
