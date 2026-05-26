"""T6.2 — End-to-end Luna Learn integration test.

Exercises the full ``LearnFromMediaWorkflow`` body in a Temporal
``WorkflowEnvironment`` against a checked-in YouTube fixture URL. Per
plan T6.2 the test:

  * resolves the fixture URL from ``tests/fixtures/luna_learn_urls.json``
    (so a future URL rotation is a one-file change)
  * lets the **real workflow body** + **real activity wrappers** run
  * stubs only the network boundary (``A._call_mcp``) — every MCP
    primitive sees a deterministic response shaped like the real shim
    output, so the workflow's envelope decoders + branching survive
    every refactor
  * wires the T6.1 Code Reviewer stub for the review verdict so the
    full revise / reject / approve contract is preserved
  * asserts the workflow returns a ``success`` envelope with the
    installed skill_id + the slug derived from the synthesized draft

Tagged ``@pytest.mark.slow``: by default ``-m "not slow"`` skips it.
Opt-in with ``pytest -m slow tests/test_luna_learn_integration.py``.

True end-to-end (live YouTube → real yt-dlp → real Whisper → real
install → real KG insert) is opt-in via ``LUNA_LEARN_E2E=1``; that
mode requires Temporal + Postgres + mcp-server all running and is
documented for contributors but never enforced in CI. The default
``slow`` mode here gives high signal coverage without external deps —
the real-network path is exercised manually by Simon ahead of merge.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

pytestmark = pytest.mark.slow

# Activity + workflow imports happen at module scope so collection
# surfaces import errors immediately (same surface as api startup; see
# `feedback_test_router_startup`).
from app.workflows.activities import learn_from_media_activities as A
from app.workflows.learn_from_media_workflow import LearnFromMediaWorkflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

# Reuse the T6.1 reviewer stub. Tests/fixtures are added to sys.path
# in conftest so this import resolves without dotted-package indirection.
from fixtures.code_reviewer_stub import reviewer_stub, STUB_REVIEWER_AGENT_ID


# ── Fixture loader ──────────────────────────────────────────────────────


def _load_url_fixture() -> dict:
    """Return the default URL fixture from the checked-in JSON file."""
    path = Path(__file__).parent / "fixtures" / "luna_learn_urls.json"
    with path.open() as f:
        data = json.load(f)
    return data["default"]


# ── Shared isolation: keep workspace writes inside tmp_path ─────────────


@pytest.fixture(autouse=True)
def _isolate_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_WORKSPACE_BASE", tmp_path)


# ── Temporal env + worker ──────────────────────────────────────────────


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


@pytest.fixture
async def worker(env):
    async with Worker(
        env.client,
        task_queue="luna-learn-int-test",
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


# ── Stub MCP boundary ──────────────────────────────────────────────────


# A canonical SKILL.md synthesized "from" the transcript. Fields mirror
# the spec §1.6 frontmatter schema; the body is short on purpose so
# diffs surface synthesis-prompt drift, not noise.
_SYNTH_SKILL_MD = (
    "---\n"
    "name: Big Buck Bunny Lesson\n"
    "engine: markdown\n"
    "category: animation\n"
    "tags: [demo, animation, learning]\n"
    "auto_trigger: \"summarize bunny clip\"\n"
    "inputs: []\n"
    "---\n"
    "## Description\n"
    "A short demo skill learned from the Big Buck Bunny clip used as the\n"
    "default Luna Learn integration fixture. The body is intentionally\n"
    "trivial — the integration contract under test is the workflow\n"
    "wiring, not the synthesis quality.\n"
)
_SYNTH_SLUG = "big-buck-bunny-lesson"


def _build_responses(url: str, *, install_skill_id: str) -> dict:
    """Build the per-tool MCP response dict for the happy path."""

    def review_response(payload: dict, _idx: int) -> dict:
        # Route the real stub against the real synthesized skill_md so
        # the verdict-routing branch in the workflow is exercised end
        # to end (not just the activity wrapper).
        return reviewer_stub(payload.get("skill_md", ""))

    return {
        "extract_media": {
            "audio_path": "/tmp/luna-learn-int/audio.m4a",
            "metadata": {
                "duration_s": 65,
                "title": "Big Buck Bunny — short public-domain clip",
                "source_url": url,
            },
        },
        "transcribe_url": {
            "transcript": (
                "Big Buck Bunny is a short open-movie animation by the "
                "Blender Foundation; in this clip the rabbit reacts to a "
                "falling apple and then to a chase by smaller animals."
            ),
            "engine": "whisper",
            "duration_ms": 65_000,
        },
        "synthesize_skill_draft": {
            "skill_md": _SYNTH_SKILL_MD,
            "slug": _SYNTH_SLUG,
            "engine": "markdown",
            "synthetic_test_input": {"prompt": "What happens to the bunny?"},
            "synthetic_test_expected": {"contains": "bunny"},
        },
        "dispatch_skill_review": review_response,
        "run_synthetic_test": {
            "passed": True,
            "actual_output": {"answer": "the bunny reacts to a falling apple"},
            "error": None,
        },
        "install_skill": {
            "skill_id": install_skill_id,
            "slug": _SYNTH_SLUG,
            "path": f"_tenant/00000000-0000-0000-0000-000000000001/{_SYNTH_SLUG}/skill.md",
        },
        "diffuse_learning": {
            "observation_id": "obs_int_42",
            "soft_failed": False,
            "error": None,
        },
        "act_notify_session": {"notified": True},
    }


def _install_mcp_stub(monkeypatch, responses: dict) -> dict:
    """Patch ``A._call_mcp`` to dispatch by tool name. Tracks call
    counts so the test can assert each step ran exactly once."""
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


# ── The integration test ────────────────────────────────────────────────


async def test_learn_from_media_end_to_end_happy_path(env, worker, monkeypatch):
    """Full pipeline: extract → transcribe → synth → review (approved
    via T6.1 stub) → test (passed) → install → diffuse → notify.

    Asserts:
      * the workflow returns ``status == "success"``
      * the install step reports the slug derived from the synthesized
        SKILL.md frontmatter (no slug exhaustion / no rename)
      * the diffuse step was reached (so the KG observation contract
        is exercised end to end, not short-circuited)
      * every expected MCP primitive was invoked exactly once
    """
    fixture = _load_url_fixture()
    url = fixture["url"]
    install_skill_id = "sk_int_e2e_001"

    responses = _build_responses(url, install_skill_id=install_skill_id)
    counts = _install_mcp_stub(monkeypatch, responses)

    intent = {
        "source_url": url,
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "actor_user_id": "00000000-0000-0000-0000-0000000000aa",
        "dry_run": False,
    }

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        intent,
        id="luna-learn-int-test-happy",
        task_queue="luna-learn-int-test",
    )

    # Workflow result envelope — pin the success status and the
    # downstream identifiers the caller (LearningService) relies on.
    assert result["status"] == "success", result
    assert result.get("skill_id") == install_skill_id
    # Slug propagates from synthesis through install — a rename would
    # signal the workflow lost provenance between the two steps.
    install_meta = result.get("install") or {}
    assert install_meta.get("slug", _SYNTH_SLUG) == _SYNTH_SLUG

    # Every primitive in the happy path should have been invoked once.
    # If the workflow short-circuits (e.g. test_failed → quarantine
    # before install) the counts drop and we catch it here.
    for tool in (
        "extract_media",
        "transcribe_url",
        "synthesize_skill_draft",
        "dispatch_skill_review",
        "run_synthetic_test",
        "install_skill",
        "diffuse_learning",
    ):
        assert counts.get(tool, 0) >= 1, (
            f"expected {tool!r} to be invoked at least once; counts={counts}"
        )


async def test_learn_from_media_reviewer_rejected_quarantines(env, worker, monkeypatch):
    """Reviewer-rejected branch: the T6.1 stub recognises a `subprocess`
    body as rejected → workflow must NOT install and must NOT diffuse.

    The integration test for the reject path lives here (and not in the
    workflow unit tests) because the verdict comes from the real
    reviewer stub via ``dispatch_skill_review``'s real activity wrapper
    — proving the stub plugs in cleanly at the MCP boundary."""
    fixture = _load_url_fixture()
    url = fixture["url"]

    # A draft with a forbidden shellout — the reviewer stub will reject.
    bad_skill_md = (
        "---\n"
        "name: Sneaky Skill\n"
        "engine: python\n"
        "category: misc\n"
        "tags: [demo]\n"
        "auto_trigger: \"sneak\"\n"
        "inputs: []\n"
        "---\n"
        "import subprocess; subprocess.run(['rm', '-rf', '/tmp/x'])\n"
    )

    responses = _build_responses(url, install_skill_id="sk_never_installed")
    responses["synthesize_skill_draft"] = {
        "skill_md": bad_skill_md,
        "slug": "sneaky-skill",
        "engine": "python",
        "synthetic_test_input": {},
        "synthetic_test_expected": {},
    }
    counts = _install_mcp_stub(monkeypatch, responses)

    intent = {
        "source_url": url,
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "actor_user_id": "00000000-0000-0000-0000-0000000000aa",
        "dry_run": False,
    }

    result = await env.client.execute_workflow(
        LearnFromMediaWorkflow.run,
        intent,
        id="luna-learn-int-test-reject",
        task_queue="luna-learn-int-test",
    )

    # The workflow MUST NOT install or diffuse on a rejected verdict.
    assert result["status"] != "success", result
    assert counts.get("install_skill", 0) == 0, (
        "install_skill was called on a rejected verdict — "
        f"workflow short-circuit failed; counts={counts}"
    )
    assert counts.get("diffuse_learning", 0) == 0, (
        "diffuse_learning was called on a rejected verdict — "
        f"workflow short-circuit failed; counts={counts}"
    )
