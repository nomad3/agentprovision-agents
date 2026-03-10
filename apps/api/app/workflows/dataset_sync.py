"""
Temporal workflow for syncing datasets to Databricks Unity Catalog
"""

from temporalio import workflow
from datetime import timedelta
from typing import Dict, Any


@workflow.defn(sandboxed=False)
class DatasetSyncWorkflow:
    """
    Durable workflow for syncing datasets to Databricks

    Steps:
    1. Create Bronze external table (raw parquet)
    2. Create Silver managed table (typed, cleaned)
    3. Update dataset metadata in PostgreSQL

    Handles:
    - Automatic retries on failure
    - Progress tracking
    - Error recovery
    """

    @workflow.run
    async def run(self, dataset_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        Execute dataset sync workflow

        Args:
            dataset_id: UUID of dataset to sync
            tenant_id: UUID of tenant (for catalog isolation)

        Returns:
            Dict with status, bronze_table, silver_table
        """
        workflow.logger.info(f"Starting dataset sync for {dataset_id}")

        try:
            # Step 1: Sync to Bronze layer
            bronze_result = await workflow.execute_activity(
                "sync_to_bronze",
                args=[dataset_id, tenant_id],
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=20),
                retry_policy=workflow.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=5),
                    maximum_interval=timedelta(minutes=2),
                    backoff_coefficient=2.0
                )
            )

            workflow.logger.info(f"Bronze table created: {bronze_result['bronze_table']}")

            # Step 2: Transform to Silver layer
            silver_result = await workflow.execute_activity(
                "transform_to_silver",
                args=[bronze_result["bronze_table"], tenant_id],
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=timedelta(minutes=20),
                retry_policy=workflow.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=2),
                    maximum_interval=timedelta(minutes=2)
                )
            )

            workflow.logger.info(f"Silver table created: {silver_result['silver_table']}")

            # Step 3: Update dataset metadata in PostgreSQL
            await workflow.execute_activity(
                "update_dataset_metadata",
                args=[dataset_id, tenant_id, bronze_result, silver_result],
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=20),
                retry_policy=workflow.RetryPolicy(
                    maximum_attempts=5,
                    maximum_interval=timedelta(minutes=2)
                )
            )

            workflow.logger.info(f"Dataset sync complete for {dataset_id}")

            return {
                "status": "synced",
                "bronze_table": bronze_result["bronze_table"],
                "silver_table": silver_result["silver_table"],
                "row_count": bronze_result.get("row_count", 0)
            }

        except Exception as e:
            workflow.logger.error(
                f"Dataset sync failed for {dataset_id}: {e}",
                exc_info=True
            )
            return {
                "status": "failed",
                "dataset_id": dataset_id,
                "tenant_id": tenant_id,
                "error": str(e)
            }
