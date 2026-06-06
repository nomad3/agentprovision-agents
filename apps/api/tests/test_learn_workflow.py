"""T3.2a–f — workflow body tests for LearnFromMediaWorkflow.

Per plan §T3.2 (NEW-IMPORTANT-2): Temporal's ``Worker`` captures activity
function references at construction time, so monkeypatching ``A.act_X``
on the module would NOT affect the in-flight worker. Instead we patch the
``_call_mcp`` HTTP boundary — every real activity calls into ``_wrap``
which calls ``_call_mcp`` — so the real activity bodies + envelope
decoders run, and only the HTTP layer is stubbed.

T3.2a — happy path.
T3.2b — extract-error per-type branches (5 typed errors → notify+quarantine).
T3.2c — review branches (revise loop, rejected, reviewer-down, timeout).
T3.2d — test_failed → quarantine + audit row.
T3.2e — diffuse soft-fail → still success, cached for retry.
T3.2f — install_failed branches (SlugExhausted / UnknownError).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.workflows.activities import learn_from_media_activities as A
from app.workflows.learn_from_media_workflow import LearnFromMediaWorkflow


@pytest.fixture(autouse=True)
def _isolate_workspace(monkeypatch, tmp_path):
    """T3.3+ activities (act_write_cache/act_write_quarantine) write to
    ``_WORKSPACE_BASE`` which defaults to ``/var/agentprovision/workspaces``
    — a path the test process can't create. Redirect every workflow test
    to a tmp dir so the quarantine/cache writes succeed (otherwise the
    activity raises PermissionError, Temporal retries forever, and the
    test hangs until pytest-timeout fires)."""
    monkeypatch.setattr(A, "_WORKSPACE_BASE", tmp_path)


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


@pytest.fixture
async def worker(env):
    async with Worker(
        env.client,
        task_queue="learn-test",
        workflows=[LearnFromMediaWorkflow],
        activities=[
            A.act_extract_media,
            A.act_transcribe_url,
            A.act_synthesize_skill_draft,
            A.act_dispatch_skill_review,
            A.act_run_synthetic_test,
            A.act_install_skill,
            A.act_diffuse_learning,
            A.act_write_cache,
            A.act_write_quarantine,
            A.act_log_test_fail,
            A.act_notify_session,
            A.act_probe_attachment,
            A.act_read_cache,
        ],
    ) as w:
        yield w


def _mock_mcp_responses(monkeypatch, responses: dict):
    """Replace ``A._call_mcp`` with a dispatcher returning per-tool stub data.

    ``responses`` keys are tool names ("extract_media", "transcribe_url",
    ...). Values are either:
    - ``dict``: raw return value the real tool would return.
    - ``Exception``: raised when the tool is called (use ``_typed_error``
      for shim-style envelopes).
    - ``callable``: called with ``(payload, call_index)`` to allow
      per-call branching (e.g. revise→approved across multiple calls).

    Unknown calls raise ``RuntimeError`` so unexpected MCP traffic surfaces
    as a test failure (per plan §T3.2 scaffolding).
    """

    call_counts: dict[str, int] = {}

    async def fake(tool: str, payload: dict):
        if tool not in responses:
            raise RuntimeError(f"unexpected MCP call to {tool!r}")
        idx = call_counts.get(tool, 0)
        call_counts[tool] = idx + 1
        value = responses[tool]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(payload, idx)
        return value

    monkeypatch.setattr(A, "_call_mcp", fake)
    return call_counts


def _typed_error(status: int, error_type: str, message: str = "boom"):
    """Build the HTTPStatusError the T1.2a shim raises for a typed error.

    The ``_wrap`` decoder reads ``response.json()["error_type"]`` as
    authoritative; the status is only the fast-path fallback.
    """
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.json = MagicMock(
        return_value={"error_type": error_type, "message": message}
    )
    return httpx.HTTPStatusError(
        message, request=MagicMock(spec=httpx.Request), response=response
    )


def _happy_responses() -> dict:
    """All-success response dict used by failure-path tests as a baseline.

    Tests override individual keys (or replace with ``_typed_error(...)``).
    """
    return {
        "extract_media": {
            "audio_path": "/tmp/x.m4a",
            "metadata": {"duration_s": 90, "title": "T"},
        },
        "transcribe_url": {
            "transcript": "hello world",
            "engine": "whisper",
            "duration_ms": 90000,
        },
        "synthesize_skill_draft": {
            "skill_md": (
                "---\n"
                "name: Fix Printer\n"
                "engine: markdown\n"
                "auto_trigger: \"Fix printer\"\n"
                "inputs: []\n"
                "---\n"
                "Unplug it"
            ),
            "slug": "fix-printer",
            "engine": "markdown",
            "synthetic_test_input": {"x": 1},
            "synthetic_test_expected": {"y": 2},
        },
        "dispatch_skill_review": {
            "verdict": "approved",
            "findings": [],
            "reviewer_agent_id": "755796a4-0000-0000-0000-000000000000",
        },
        "run_synthetic_test": {
            "passed": True,
            "actual_output": {"y": 2},
            "error": None,
        },
        "install_skill": {
            "skill_id": "s1",
            "path": "/x/_tenant/t1/fix-printer/skill.md",
        },
        "diffuse_learning": {"observation_id": "obs1", "soft_failed": False},
    }


@pytest.mark.asyncio
async def test_workflow_happy_path(env, worker, monkeypatch):
    _mock_mcp_responses(
        monkeypatch,
        {
            "extract_media": {
                "audio_path": "/tmp/x.m4a",
                "metadata": {"duration_s": 90, "title": "T"},
            },
            "transcribe_url": {
                "transcript": "hello world",
                "engine": "whisper",
                "duration_ms": 90000,
            },
            "synthesize_skill_draft": {
                "skill_md": (
                    "---\n"
                    "name: Fix Printer\n"
                    "engine: markdown\n"
                    "auto_trigger: \"Fix printer\"\n"
                    "inputs: []\n"
                    "---\n"
                    "Unplug it"
                ),
                "slug": "fix-printer",
                "engine": "markdown",
                "synthetic_test_input": {"x": 1},
                "synthetic_test_expected": {"y": 2},
            },
            "dispatch_skill_review": {
                "verdict": "approved",
                "findings": [],
                "reviewer_agent_id": "755796a4-0000-0000-0000-000000000000",
            },
            "run_synthetic_test": {
                "passed": True,
                "actual_output": {"y": 2},
                "error": None,
            },
            "install_skill": {
                "skill_id": "s1",
                "path": "/x/_tenant/t1/fix-printer/skill.md",
            },
            "diffuse_learning": {"observation_id": "obs1", "soft_failed": False},
        },
    )
    # ``act_notify_session`` would write to the session DB; stub at the
    # DB-write boundary so we never hit a real connection. Use
    # ``raising=False`` because the helper symbol lands in T3.5; for the
    # happy-path test no session_id is supplied, so notify is never called.
    monkeypatch.setattr(
        A, "_write_session_message", lambda *a, **k: None, raising=False
    )
    # ``act_transcribe_url``'s success path deletes the audio file; create
    # it so the unlink doesn't error.
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc123",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-happy",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert result["skill_id"] == "s1"
    assert "fix-printer" in result["skill_path"]
    assert result["skill_name"] == "Fix Printer"


# ---------------------------------------------------------------------------
# T3.2b — extract-error per-type branches
# ---------------------------------------------------------------------------

_EXTRACT_ERROR_CASES = [
    (451, "MediaPrivate", "requires sign-in"),
    (404, "MediaNotFound", "doesn't exist or has been removed"),
    (403, "MediaGeoBlocked", "geo-blocked"),
    (429, "MediaAntiScrape", "rate-limiting"),
    (413, "MediaTooLong", "15-minute cap"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error_type,phrase", _EXTRACT_ERROR_CASES)
async def test_workflow_extract_error_branch(
    env, worker, monkeypatch, status, error_type, phrase
):
    """T3.2b — each typed extract error → notify_message per spec §3 +
    quarantine write. No subsequent activities are called (extract is
    step 1; if any later tool is invoked the _mock_mcp_responses helper
    raises RuntimeError → test fail)."""
    _mock_mcp_responses(
        monkeypatch,
        {"extract_media": _typed_error(status, error_type)},
    )

    wf_id = f"test-extract-{error_type.lower()}"
    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc123",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id=wf_id,
        task_queue="learn-test",
    )
    assert result["status"] == "extract_failed"
    assert result["error"]["type"] == error_type
    assert phrase in result["notify_message"]


@pytest.mark.asyncio
async def test_workflow_extract_unknown_error_uses_generic_notify(
    env, worker, monkeypatch
):
    """T3.2b — unrecognised error.type still gets a generic notify so the
    user isn't left in the dark (spec §3 catch-all row)."""
    _mock_mcp_responses(
        monkeypatch,
        {"extract_media": _typed_error(500, "UnknownError", "weird")},
    )
    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc123",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-extract-unknown",
        task_queue="learn-test",
    )
    assert result["status"] == "extract_failed"
    assert "UnknownError" in result["notify_message"]


# ---------------------------------------------------------------------------
# T3.2c — review branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_review_revise_then_approved(env, worker, monkeypatch):
    """T3.2c — revise verdict on attempt 0 → reviewer findings become hints
    in attempt 1's synth call → approved → install proceeds (success)."""
    responses = _happy_responses()
    # Track which synth call we're on, to verify hints flow.
    synth_payloads: list[dict] = []

    def synth_cb(payload, idx):
        synth_payloads.append(payload)
        return _happy_responses()["synthesize_skill_draft"]

    def review_cb(payload, idx):
        if idx == 0:
            return {
                "verdict": "revise",
                "findings": ["use kebab-case for slug", "tighten body"],
                "reviewer_agent_id": "rev-1",
            }
        return {
            "verdict": "approved",
            "findings": [],
            "reviewer_agent_id": "rev-1",
        }

    responses["synthesize_skill_draft"] = synth_cb
    responses["dispatch_skill_review"] = review_cb
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-revise-approved",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    # Synth was called twice; second call's payload carries the reviewer
    # findings as hints.
    assert len(synth_payloads) == 2
    assert synth_payloads[0]["hints"] == []
    assert synth_payloads[1]["hints"] == [
        "use kebab-case for slug",
        "tighten body",
    ]


@pytest.mark.asyncio
async def test_workflow_review_revise_exhausted(env, worker, monkeypatch):
    """T3.2c — revise × (max+1) attempts → revise_exhausted → quarantine.

    Default max_revise = 2 so we allow attempt 0 + 2 revisions = 3 total
    review calls, all returning ``revise``.
    """
    responses = _happy_responses()
    responses["dispatch_skill_review"] = {
        "verdict": "revise",
        "findings": ["still wrong"],
        "reviewer_agent_id": "rev-1",
    }
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-revise-exhausted",
        task_queue="learn-test",
    )
    assert result["status"] == "revise_exhausted"
    # Default max_revise = 2 → initial synth + 2 retries = 3 attempts, all
    # returning ``revise``. ``revise_attempts`` counts every revise verdict.
    assert result["revise_attempts"] == 3
    assert "still wrong" in result["notify_message"]


@pytest.mark.asyncio
async def test_workflow_review_rejected(env, worker, monkeypatch):
    """T3.2c — verdict ``rejected`` → quarantine + notify with reason."""
    responses = _happy_responses()
    responses["dispatch_skill_review"] = {
        "verdict": "rejected",
        "findings": ["script forbidden by policy"],
        "reviewer_agent_id": "rev-1",
    }
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-rejected",
        task_queue="learn-test",
    )
    assert result["status"] == "rejected"
    assert result["findings"] == ["script forbidden by policy"]
    assert "script forbidden by policy" in result["notify_message"]


@pytest.mark.asyncio
async def test_workflow_review_reviewer_not_provisioned_caches(
    env, worker, monkeypatch
):
    """T3.2c — ReviewerNotProvisioned (503) is RECOVERABLE per spec §3:
    workflow caches state, notifies with ``--resume-last`` hint, returns
    ``review_unavailable`` (NOT ``review_failed``)."""
    responses = _happy_responses()
    responses["dispatch_skill_review"] = _typed_error(
        503, "ReviewerNotProvisioned", "agent not in tenant"
    )
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-reviewer-down",
        task_queue="learn-test",
    )
    assert result["status"] == "review_unavailable"
    assert result["cached"] is True
    assert "--resume-last" in result["notify_message"]
    assert result["error"]["type"] == "ReviewerNotProvisioned"


@pytest.mark.asyncio
async def test_workflow_review_timeout_quarantines(env, worker, monkeypatch):
    """T3.2c — ReviewTimeout (504) is TERMINAL per spec §3: quarantine, no
    resume hint. The distinction from ``ReviewerNotProvisioned`` is what
    reviewer flagged (I6)."""
    responses = _happy_responses()
    responses["dispatch_skill_review"] = _typed_error(
        504, "ReviewTimeout", "60s exceeded"
    )
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-review-timeout",
        task_queue="learn-test",
    )
    assert result["status"] == "review_failed"
    assert result["error"]["type"] == "ReviewTimeout"
    assert "--resume-last" not in result["notify_message"]


# ---------------------------------------------------------------------------
# T3.2d — test_failed → quarantine + audit row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_test_failed_quarantines(env, worker, monkeypatch):
    """T3.2d — run_synthetic_test returns ``passed: False`` →
    workflow writes a library_revisions audit row (act_log_test_fail) +
    quarantines the draft. No install attempted.

    The stubs for act_log_test_fail and act_write_quarantine return
    ``{ok: True, ...}`` envelopes so the workflow proceeds through both;
    real bodies land in T4.4e (audit) and T3.3 (quarantine). Failure to
    reach either would surface as a worker error or wrong return status.
    """
    responses = _happy_responses()
    responses["run_synthetic_test"] = {
        "passed": False,
        "actual_output": {"y": 99},
        "error": "expected y=2 got y=99",
    }
    # If the workflow accidentally proceeds to install / diffuse, those
    # entries are still present in _happy_responses; with the correct
    # branching they should NEVER be called. We can't easily assert
    # "not called" without an interceptor, but the returned status is
    # ``test_failed`` (not ``success``) which proves the branch fired
    # before install.
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-test-failed",
        task_queue="learn-test",
    )
    assert result["status"] == "test_failed"
    assert "expected y=2" in result["error"]
    assert "quarantined" in result["notify_message"]


@pytest.mark.asyncio
async def test_workflow_test_step_envelope_error(env, worker, monkeypatch):
    """T3.2d — run_synthetic_test itself errors (e.g. transient code-worker
    failure) → workflow still treats it as test_failed and quarantines.
    The error string comes from the envelope's ``error.type`` so user-facing
    notify can mention the underlying cause."""
    responses = _happy_responses()
    responses["run_synthetic_test"] = _typed_error(500, "UnknownError", "worker died")
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-test-envelope-err",
        task_queue="learn-test",
    )
    assert result["status"] == "test_failed"
    # ``error`` is the envelope dict, not a string, when the step itself failed.
    assert result["error"]["type"] == "UnknownError"


# ---------------------------------------------------------------------------
# T3.2e — diffuse soft-fail → cache, install survives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_diffuse_soft_fail_still_success(env, worker, monkeypatch):
    """T3.2e — diffuse_learning returns ``soft_failed: True``:
    install already happened so the skill is usable; cache the pending
    diffusion + return ``success`` with ``diffuse_cached: true``."""
    responses = _happy_responses()
    responses["diffuse_learning"] = {
        "observation_id": None,
        "soft_failed": True,
    }
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-diffuse-soft-fail",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert result["diffuse_cached"] is True
    assert result["skill_id"] == "s1"


@pytest.mark.asyncio
async def test_workflow_diffuse_envelope_error_still_success(
    env, worker, monkeypatch
):
    """T3.2e — diffuse step ENVELOPE fails (KG unreachable / 5xx) → same
    soft-fail handling: install survives, cache written, success returned.
    """
    responses = _happy_responses()
    responses["diffuse_learning"] = _typed_error(500, "UnknownError", "kg down")
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-diffuse-envelope-err",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert result["diffuse_cached"] is True


@pytest.mark.asyncio
async def test_workflow_diffuse_success_no_cache_key(env, worker, monkeypatch):
    """T3.2e — happy diffuse path should NOT set ``diffuse_cached`` (the
    key is only added on soft-fail, so callers can distinguish)."""
    responses = _happy_responses()
    # default ``diffuse_learning`` is {soft_failed: False}.
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-diffuse-success",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert "diffuse_cached" not in result


# ---------------------------------------------------------------------------
# T3.2f — install_failed branches (workflow-side; server-side DB+FS
# rollback lands in T4.4e)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_install_slug_exhausted(env, worker, monkeypatch):
    """T3.2f — install raises SlugExhausted (409): workflow quarantines
    the reviewed+tested draft and returns ``install_failed`` with a
    user-facing notify message that nudges towards ``--slug`` or rename.
    The real DB-side serialization that produces SlugExhausted after 5
    retries lives in T4.4e."""
    responses = _happy_responses()
    responses["install_skill"] = _typed_error(
        409, "SlugExhausted", "5 retries exhausted"
    )
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-install-slug-exhausted",
        task_queue="learn-test",
    )
    assert result["status"] == "install_failed"
    assert result["error"]["type"] == "SlugExhausted"
    assert "slug" in result["notify_message"]


@pytest.mark.asyncio
async def test_workflow_install_unknown_error(env, worker, monkeypatch):
    """T3.2f — install raises an unknown error (500 / non-typed): workflow
    still quarantines + returns install_failed with the generic message.

    The reviewer-flagged B4 case (DB error mid-transaction, FS-rollback
    after row reserved) manifests to the workflow as exactly this
    envelope shape, validated server-side in T4.4e."""
    responses = _happy_responses()
    responses["install_skill"] = _typed_error(
        500, "UnknownError", "db connection refused"
    )
    _mock_mcp_responses(monkeypatch, responses)
    Path("/tmp/x.m4a").write_bytes(b"x")

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "source_url": "https://youtu.be/abc",
            "tenant_id": "t1",
            "actor_user_id": "u1",
        },
        id="test-install-unknown-error",
        task_queue="learn-test",
    )
    assert result["status"] == "install_failed"
    assert result["error"]["type"] == "UnknownError"
    assert "quarantined" in result["notify_message"]


# ---------------------------------------------------------------------------
# T3.4 — resume path (reviewer-down + KG-down)
# ---------------------------------------------------------------------------

_HAPPY_DRAFT = {
    "skill_md": (
        "---\n"
        "name: Fix Printer\n"
        "engine: markdown\n"
        "auto_trigger: \"Fix printer\"\n"
        "inputs: []\n"
        "tags: [hardware]\n"
        "---\n"
        "Unplug it"
    ),
    "slug": "fix-printer",
    "engine": "markdown",
    "synthetic_test_input": {"x": 1},
    "synthetic_test_expected": {"y": 2},
}


@pytest.mark.asyncio
async def test_workflow_resume_reviewer_down(env, worker, monkeypatch, tmp_path):
    """T3.4 — reviewer-down resume: cache holds transcript + draft only
    (no review.json, no test.json). Workflow re-dispatches
    ``dispatch_skill_review`` against the cached draft and proceeds through
    test → install → diffuse → success. ``extract_media`` and
    ``transcribe_url`` MUST NOT be called (they're the expensive steps the
    resume path exists to skip)."""
    # Point the cache at a tmp_path so we control the on-disk state.
    monkeypatch.setattr(A, "_WORKSPACE_BASE", tmp_path)
    # Seed the reviewer-down cache shape (transcript + draft, no review,
    # no test) per the T3.4 contract.
    job_id = "resume-job-reviewer-down"
    cdir = tmp_path / "_tenant" / "t1" / "_learning_cache" / job_id
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "transcript.txt").write_text("hello world")
    (cdir / "draft.md").write_text(_HAPPY_DRAFT["skill_md"])
    import json as _json
    (cdir / "draft.json").write_text(_json.dumps(_HAPPY_DRAFT))

    # Only the post-cache steps should hit MCP. extract / transcribe /
    # synth are NOT in the responses dict so _mock_mcp_responses raises
    # RuntimeError → test fail if the workflow tries to call them.
    _mock_mcp_responses(
        monkeypatch,
        {
            "dispatch_skill_review": {
                "verdict": "approved",
                "findings": [],
                "reviewer_agent_id": "rev-1",
            },
            "run_synthetic_test": {
                "passed": True,
                "actual_output": {"y": 2},
                "error": None,
            },
            "install_skill": {
                "skill_id": "s1",
                "path": "/x/_tenant/t1/fix-printer/skill.md",
            },
            "diffuse_learning": {"observation_id": "obs1", "soft_failed": False},
        },
    )

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "tenant_id": "t1",
            "actor_user_id": "u1",
            "resume_job_id": job_id,
        },
        id="test-resume-reviewer-down",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert result["resumed"] is True
    assert result["skill_id"] == "s1"
    assert result["skill_name"] == "Fix Printer"


@pytest.mark.asyncio
async def test_workflow_resume_kg_down(env, worker, monkeypatch, tmp_path):
    """T3.4 — KG-down resume: cache holds transcript + draft + review +
    test.install (skill already installed). Workflow retries
    ``diffuse_learning`` ONLY — no extract, no transcribe, no synth, no
    review, no test, no install. Success returns the cached install info
    with ``resumed: true``."""
    monkeypatch.setattr(A, "_WORKSPACE_BASE", tmp_path)
    job_id = "resume-job-kg-down"
    cdir = tmp_path / "_tenant" / "t1" / "_learning_cache" / job_id
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "transcript.txt").write_text("hello world")
    (cdir / "draft.md").write_text(_HAPPY_DRAFT["skill_md"])
    import json as _json
    (cdir / "draft.json").write_text(_json.dumps(_HAPPY_DRAFT))
    (cdir / "review.json").write_text(
        _json.dumps(
            {
                "verdict": "approved",
                "findings": [],
                "reviewer_agent_id": "rev-1",
            }
        )
    )
    (cdir / "test.json").write_text(
        _json.dumps(
            {
                "install": {
                    "skill_id": "s-existing",
                    "path": "/x/_tenant/t1/fix-printer/skill.md",
                    "capabilities": ["Fix printer", "hardware"],
                },
                "soft_failed_diffuse": True,
            }
        )
    )

    # Only diffuse_learning is allowed — every other MCP call raises.
    _mock_mcp_responses(
        monkeypatch,
        {
            "diffuse_learning": {
                "observation_id": "obs-resumed",
                "soft_failed": False,
            },
        },
    )

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "tenant_id": "t1",
            "actor_user_id": "u1",
            "resume_job_id": job_id,
        },
        id="test-resume-kg-down",
        task_queue="learn-test",
    )
    assert result["status"] == "success"
    assert result["resumed"] is True
    assert result["skill_id"] == "s-existing"
    assert result["skill_path"] == "/x/_tenant/t1/fix-printer/skill.md"
    # diffuse_cached must NOT be set: this resume succeeded, no soft-fail.
    assert "diffuse_cached" not in result


@pytest.mark.asyncio
async def test_workflow_resume_cache_not_found(env, worker, monkeypatch, tmp_path):
    """T3.4 — resume with a job_id that has no cache directory returns
    ``resume_cache_not_found`` so the caller knows to re-dispatch fresh
    instead of silently re-running the full pipeline."""
    monkeypatch.setattr(A, "_WORKSPACE_BASE", tmp_path)
    # No MCP calls allowed — workflow must short-circuit on the cache miss
    # without touching extract/transcribe/anything else.
    _mock_mcp_responses(monkeypatch, {})

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        {
            "tenant_id": "t1",
            "actor_user_id": "u1",
            "resume_job_id": "no-such-job",
        },
        id="test-resume-not-found",
        task_queue="learn-test",
    )
    assert result["status"] == "resume_cache_not_found"
    assert result["job_id"] == "no-such-job"
    assert result["error"]["type"] == "CacheNotFound"
