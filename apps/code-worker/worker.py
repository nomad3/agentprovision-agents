"""Temporal worker for code tasks -- runs Claude Code CLI."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from workflows import (
    CodeTaskWorkflow, execute_code_task,
    ChatCliWorkflow, execute_chat_cli,
    ProviderReviewWorkflow, review_with_claude, review_with_codex,
    review_with_local_gemma, finalize_provider_council,
    FanoutChatCliWorkflow,
)
# Audio transcription was migrated out of apps/api (see docs/plans/
# 2026-05-18-docker-image-shrink-and-latency.md, Phase A). The workflow +
# activity register on the existing ``agentprovision-code`` queue so the
# api can dispatch by workflow id without provisioning a second worker.
from transcription import TranscribeAudioWorkflow, transcribe_audio_activity

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
TASK_QUEUE = "agentprovision-code"


async def main():
    logger.info("Connecting to Temporal at %s", TEMPORAL_ADDRESS)
    client = await Client.connect(TEMPORAL_ADDRESS)

    logger.info("Starting code worker on queue '%s'", TASK_QUEUE)
    # execute_chat_cli is a sync (non-async) activity that runs blocking
    # subprocess calls.  Temporal requires an activity_executor for sync
    # activities so they run in a thread pool instead of the event loop.
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            CodeTaskWorkflow,
            ChatCliWorkflow,
            ProviderReviewWorkflow,
            FanoutChatCliWorkflow,  # #177 Phase 1 ship — parallel fanout
            TranscribeAudioWorkflow,  # api-image-diet Phase A
        ],
        activities=[
            execute_code_task, execute_chat_cli,
            review_with_claude, review_with_codex,
            review_with_local_gemma, finalize_provider_council,
            transcribe_audio_activity,
        ],
        activity_executor=ThreadPoolExecutor(max_workers=10),
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                "httpx", "subprocess", "asyncio",
            )
        ),
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
