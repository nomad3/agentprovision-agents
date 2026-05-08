"""End-to-end workflow tests using ``temporalio.testing.WorkflowEnvironment``.

These spin up an in-memory Temporal time-skipping test server (no live
network, no docker) and register the real ``CodeTaskWorkflow`` /
``ChatCliWorkflow`` against mocked activity stubs. We then start the
workflow, await its result, and assert on:

  1. The workflow returns the activity's result intact.
  2. The activity is dispatched exactly once.
  3. The activity receives the same input dataclass the workflow accepted.

This is the canonical Temporal workflow test pattern — ``execute_activity``
inside the workflow is the seam we're testing, not the activity body itself
(that's covered in ``test_execute_code_task.py``).
"""
from __future__ import annotations

import concurrent.futures
import uuid

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

import workflows as wf


# Pass-through sandbox restrictions — the production workflows.py does
# subprocess imports at module load. The test harness's default sandbox
# blocks those, so we relax restrictions for the worker. This is safe in
# tests because we never run real activities — only stubs that ignore
# subprocess entirely.
_PASSTHROUGH_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "workflows",
        "subprocess",
        "httpx",
    ),
)


# ── Mocked activity stubs ────────────────────────────────────────────────
#
# We re-define matching @activity.defn functions with the same NAMES as
# the real activities. Temporal dispatches activities by name, so the
# workflow doesn't know (or care) that the body changed. We can't reuse
# the real activity functions because they would invoke subprocess calls,
# httpx, and the host filesystem — all of which would break inside the
# in-memory test server.

@activity.defn(name="execute_code_task")
async def _stub_execute_code_task(task_input: wf.CodeTaskInput) -> wf.CodeTaskResult:
    """Return a deterministic CodeTaskResult so the workflow has something
    to pass through ``workflow.execute_activity``."""
    return wf.CodeTaskResult(
        pr_url="https://github.com/x/y/pull/1",
        summary=f"Stubbed: {task_input.task_description[:30]}",
        branch="code/feat/test",
        files_changed=["a.py"],
        claude_output="ok",
        success=True,
    )


@activity.defn(name="execute_chat_cli")
def _stub_execute_chat_cli(task_input: wf.ChatCliInput) -> wf.ChatCliResult:
    """Sync activity stub matching ``execute_chat_cli`` signature."""
    return wf.ChatCliResult(
        response_text=f"Echo: {task_input.message}",
        success=True,
        metadata={"platform": task_input.platform},
    )


# ── WorkflowEnvironment fixture ──────────────────────────────────────────

@pytest.fixture
async def workflow_env():
    """Spin up a time-skipping in-memory Temporal env."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


# ── CodeTaskWorkflow ──────────────────────────────────────────────────────

class TestCodeTaskWorkflowRun:
    async def test_workflow_dispatches_activity_and_returns_result(self, workflow_env):
        client: Client = workflow_env.client
        task_queue = f"phase4-5-test-{uuid.uuid4()}"

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[wf.CodeTaskWorkflow],
            activities=[_stub_execute_code_task],
            workflow_runner=_PASSTHROUGH_RUNNER,
        ):
            handle = await client.start_workflow(
                wf.CodeTaskWorkflow.run,
                wf.CodeTaskInput(
                    task_description="Add a comment",
                    tenant_id="tenant-aaa",
                ),
                id=f"code-task-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            result = await handle.result()

        assert isinstance(result, wf.CodeTaskResult)
        assert result.success is True
        assert result.pr_url == "https://github.com/x/y/pull/1"
        assert "Add a comment" in result.summary

    async def test_workflow_propagates_failure_result(self, workflow_env):
        """When the activity returns ``success=False``, the workflow returns
        that result intact (no retry — it's not an exception)."""

        @activity.defn(name="execute_code_task")
        async def _failing(task_input):
            return wf.CodeTaskResult(
                pr_url="", summary="", branch="b",
                files_changed=[], claude_output="", success=False,
                error="boom",
            )

        client = workflow_env.client
        task_queue = f"phase4-5-fail-{uuid.uuid4()}"

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[wf.CodeTaskWorkflow],
            activities=[_failing],
            workflow_runner=_PASSTHROUGH_RUNNER,
        ):
            handle = await client.start_workflow(
                wf.CodeTaskWorkflow.run,
                wf.CodeTaskInput(task_description="x", tenant_id="t"),
                id=f"code-task-fail-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            result = await handle.result()

        assert result.success is False
        assert result.error == "boom"


# ── ChatCliWorkflow ──────────────────────────────────────────────────────

class TestChatCliWorkflowRun:
    async def test_workflow_passes_input_through_to_activity(self, workflow_env):
        client = workflow_env.client
        task_queue = f"phase4-5-chat-{uuid.uuid4()}"

        # Sync activities require an executor (matches production —
        # ``execute_chat_cli`` is a sync ``@activity.defn`` and the real
        # worker.py constructs a thread pool for the same reason).
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                client,
                task_queue=task_queue,
                workflows=[wf.ChatCliWorkflow],
                activities=[_stub_execute_chat_cli],
                activity_executor=executor,
                workflow_runner=_PASSTHROUGH_RUNNER,
            ):
                handle = await client.start_workflow(
                    wf.ChatCliWorkflow.run,
                    wf.ChatCliInput(
                        platform="claude_code",
                        message="hello",
                        tenant_id="tenant-aaa",
                    ),
                    id=f"chat-{uuid.uuid4()}",
                    task_queue=task_queue,
                )
                result = await handle.result()

        assert isinstance(result, wf.ChatCliResult)
        assert result.success is True
        assert result.response_text == "Echo: hello"
        assert result.metadata["platform"] == "claude_code"
