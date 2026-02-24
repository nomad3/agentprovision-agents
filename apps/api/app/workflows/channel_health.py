"""
Temporal workflow for monitoring WhatsApp channel health.

Long-running workflow (one per tenant) that periodically checks connection
status and reconnects disconnected clients. Uses continue_as_new to avoid
history growth.
"""

from temporalio import workflow
from datetime import timedelta
from typing import Dict, Any


@workflow.defn(sandboxed=False)
class ChannelHealthMonitorWorkflow:
    """
    Periodic health monitor for WhatsApp channels.

    Runs every 60s: check status → reconnect if needed → update DB → continue_as_new.
    One workflow instance per tenant.
    """

    @workflow.run
    async def run(self, tenant_id: str, check_interval_seconds: int = 60) -> Dict[str, Any]:
        retry_policy = workflow.RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
        )

        workflow.logger.info(f"Channel health check for tenant {tenant_id[:8]}")

        # Step 1: Check all channel accounts for this tenant
        status_report = await workflow.execute_activity(
            "check_channel_health",
            args=[tenant_id],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=retry_policy,
        )

        # Step 2: Reconnect any disconnected accounts
        disconnected = status_report.get("disconnected", [])
        for account_id in disconnected:
            workflow.logger.info(f"Reconnecting {tenant_id[:8]}:{account_id}")
            await workflow.execute_activity(
                "reconnect_channel",
                args=[tenant_id, account_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry_policy,
            )

        # Step 3: Update health status in DB
        await workflow.execute_activity(
            "update_channel_health_status",
            args=[tenant_id, status_report],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=retry_policy,
        )

        # Sleep then continue as new to prevent history growth
        await workflow.sleep(timedelta(seconds=check_interval_seconds))
        workflow.continue_as_new(args=[tenant_id, check_interval_seconds])
