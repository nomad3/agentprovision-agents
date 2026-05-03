"""Smoke tests for the Temporal workflow & dataclass shapes.

We don't run these against a live Temporal cluster — we just exercise that
the workflow classes have the expected ``run`` method and that the
dataclasses round-trip.
"""
from __future__ import annotations

import dataclasses

import pytest

import workflows as wf


class TestDataclasses:
    def test_code_task_input_round_trip(self):
        ti = wf.CodeTaskInput(task_description="x", tenant_id="t", context="c")
        as_dict = dataclasses.asdict(ti)
        assert as_dict == {"task_description": "x", "tenant_id": "t", "context": "c"}

    def test_code_task_result_default_error(self):
        r = wf.CodeTaskResult(
            pr_url="u", summary="s", branch="b", files_changed=[],
            claude_output="o", success=True,
        )
        assert r.error is None

    def test_chat_cli_input_defaults(self):
        ci = wf.ChatCliInput(
            platform="claude_code", message="hi", tenant_id="t",
        )
        assert ci.instruction_md_content == ""
        assert ci.image_b64 == ""
        assert ci.session_id == ""

    def test_chat_cli_result_defaults(self):
        r = wf.ChatCliResult(response_text="ok", success=True)
        assert r.error is None
        assert r.metadata is None

    def test_agent_review_round_trip(self):
        ar = wf.AgentReview(
            agent_role="X", approved=True, verdict="APPROVED",
            issues=[], suggestions=["s"], summary="ok",
        )
        assert ar.approved is True


class TestWorkflowClassShape:
    def test_chatcli_workflow_has_run(self):
        assert hasattr(wf.ChatCliWorkflow, "run")
        assert callable(wf.ChatCliWorkflow.run)

    def test_codetask_workflow_has_run(self):
        assert hasattr(wf.CodeTaskWorkflow, "run")

    def test_provider_review_workflow_has_run(self):
        assert hasattr(wf.ProviderReviewWorkflow, "run")

    def test_provider_council_workflow_has_run(self):
        assert hasattr(wf.ProviderCouncilWorkflow, "run")


class TestModuleConstants:
    def test_workspace_path(self):
        assert wf.WORKSPACE == "/workspace"

    def test_timeout_constants_sane(self):
        assert wf.CODE_TASK_HEARTBEAT_SECONDS > 0
        assert wf.CODE_TASK_ACTIVITY_TIMEOUT_MINUTES > 0
        assert wf.CODE_TASK_SCHEDULE_TIMEOUT_MINUTES > wf.CODE_TASK_ACTIVITY_TIMEOUT_MINUTES

    def test_credit_pattern_lists_non_empty(self):
        assert wf.CLAUDE_CREDIT_ERROR_PATTERNS
        assert wf.CODEX_CREDIT_ERROR_PATTERNS
        assert wf.COPILOT_CREDIT_ERROR_PATTERNS

    def test_integration_messages_present_for_known_clis(self):
        for k in ("claude_code", "codex", "gemini_cli", "copilot_cli"):
            assert k in wf._INTEGRATION_NOT_CONNECTED_MESSAGES
            assert "not connected" in wf._INTEGRATION_NOT_CONNECTED_MESSAGES[k].lower()


# ── Provider review activities (currently stubs) ────────────────────────

class TestProviderReviewActivities:
    """The three review_with_* activities are placeholder stubs that
    currently return a hard-coded approval. Test that contract so a future
    behavioural change is intentional, not silent."""

    @pytest.mark.asyncio
    async def test_review_with_claude_returns_approval(self):
        inp = wf.ProviderCouncilInput(
            tenant_id="t", user_message="m", providers=["claude"],
            agent_slug="luna", channel="chat",
        )
        out = await wf.review_with_claude(inp, "/tmp/sess")
        assert out.approved is True
        assert out.verdict == "APPROVED"

    @pytest.mark.asyncio
    async def test_review_with_codex_returns_approval(self):
        inp = wf.ProviderCouncilInput(
            tenant_id="t", user_message="m", providers=["codex"],
            agent_slug="luna", channel="chat",
        )
        out = await wf.review_with_codex(inp, "/tmp/sess")
        assert out.provider == "codex"

    @pytest.mark.asyncio
    async def test_review_with_local_gemma_returns_approval(self):
        inp = wf.ProviderCouncilInput(
            tenant_id="t", user_message="m", providers=["local_gemma"],
            agent_slug="luna", channel="chat",
        )
        out = await wf.review_with_local_gemma(inp, "/tmp/sess")
        assert out.provider == "local_gemma"


# ── _run_review_agent (one easy branch — subprocess failure) ────────────

class TestRunReviewAgent:
    def test_subprocess_nonzero_returns_rejected(self, monkeypatch):
        import subprocess as sp

        def fake_run(*a, **kw):
            return sp.CompletedProcess(args=[], returncode=2, stdout="", stderr="boom")

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        out = wf._run_review_agent(
            role="Architect Reviewer",
            review_prompt="please review",
            extra_env={},
        )
        assert out.approved is False
        assert out.verdict == "REJECTED"
        assert "process failed" in out.issues[0].lower()

    def test_parses_structured_json_review(self, monkeypatch):
        import subprocess as sp
        import json

        review_payload = {
            "approved": True,
            "verdict": "APPROVED",
            "issues": [],
            "suggestions": ["nit: add test"],
            "summary": "looks good",
        }
        outer = {"result": json.dumps(review_payload)}

        def fake_run(*a, **kw):
            return sp.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(outer), stderr="",
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        out = wf._run_review_agent(
            role="Technical Reviewer",
            review_prompt="review",
            extra_env={},
        )
        assert out.approved is True
        assert out.verdict == "APPROVED"
        assert "nit: add test" in out.suggestions

    def test_unparseable_falls_back_to_text_scan(self, monkeypatch):
        import subprocess as sp

        def fake_run(*a, **kw):
            return sp.CompletedProcess(
                args=[], returncode=0,
                stdout="this output cannot be parsed as JSON",
                stderr="",
            )

        monkeypatch.setattr(wf.subprocess, "run", fake_run)
        out = wf._run_review_agent(role="X", review_prompt="r", extra_env={})
        # Lenient fallback returns CONDITIONAL with parse error noted.
        assert out.verdict == "CONDITIONAL"
