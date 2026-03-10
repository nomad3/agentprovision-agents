"""Temporal workflow for periodic competitor monitoring.

Long-running workflow (one per tenant) that periodically checks competitor
activity by scraping websites/news, checking ad libraries, analyzing changes,
storing observations, and creating notifications.

Uses continue_as_new to prevent history growth (same as InboxMonitorWorkflow).
"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Optional


@workflow.defn(sandboxed=False)
class CompetitorMonitorWorkflow:
    """Periodic competitor monitor. One instance per tenant.

    Runs every N seconds (default 24h):
    fetch competitors → scrape activity → check ad libraries →
    analyze changes → store observations → create notifications → sleep → continue_as_new

    Workflow ID: competitor-monitor-{tenant_id}
    """

    @workflow.run
    async def run(
        self,
        tenant_id: str,
        check_interval_seconds: int = 86400,  # 24 hours default
        last_run_summary: Optional[str] = None,
    ) -> dict:
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=30),
            backoff_coefficient=2.0,
        )
        activity_timeout = timedelta(minutes=3)

        workflow.logger.info(f"Competitor monitor cycle for tenant {tenant_id[:8]}")

        # Step 1: Fetch competitor entities from knowledge graph
        competitors = await workflow.execute_activity(
            "fetch_competitors",
            args=[tenant_id],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry_policy,
        )

        if not competitors:
            workflow.logger.info("No competitors found, sleeping until next cycle")
            await workflow.sleep(timedelta(seconds=check_interval_seconds))
            workflow.continue_as_new(args=[
                tenant_id,
                check_interval_seconds,
                last_run_summary,
            ])

        # Step 2: Scrape competitor websites and news
        scrape_results = await workflow.execute_activity(
            "scrape_competitor_activity",
            args=[tenant_id, competitors],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Step 3: Check public ad libraries
        ad_results = await workflow.execute_activity(
            "check_ad_libraries",
            args=[tenant_id, competitors],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Step 4: Analyze changes vs previous observations
        analysis = await workflow.execute_activity(
            "analyze_competitor_changes",
            args=[tenant_id, competitors, scrape_results, ad_results, last_run_summary],
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy,
        )

        # Step 5: Store observations on knowledge entities
        await workflow.execute_activity(
            "store_competitor_observations",
            args=[tenant_id, analysis],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry_policy,
        )

        # Step 6: Create notifications for notable changes
        await workflow.execute_activity(
            "create_competitor_notifications",
            args=[tenant_id, analysis],
            start_to_close_timeout=activity_timeout,
            retry_policy=retry_policy,
        )

        new_summary = analysis.get("summary", "")

        # Sleep then continue as new
        await workflow.sleep(timedelta(seconds=check_interval_seconds))

        workflow.continue_as_new(args=[
            tenant_id,
            check_interval_seconds,
            new_summary,
        ])
