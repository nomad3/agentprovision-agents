"""Temporal worker for dev tasks -- runs Claude Code CLI."""

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from workflows import DevTaskWorkflow, execute_dev_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "temporal:7233")
TASK_QUEUE = "servicetsunami-dev"


async def main():
    logger.info("Connecting to Temporal at %s", TEMPORAL_ADDRESS)
    client = await Client.connect(TEMPORAL_ADDRESS)

    logger.info("Starting dev worker on queue '%s'", TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DevTaskWorkflow],
        activities=[execute_dev_task],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
