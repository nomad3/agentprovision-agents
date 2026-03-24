"""
Temporal activities for Databricks dataset synchronization
"""

from temporalio import activity
from typing import Dict, Any
from datetime import datetime

from app.services.mcp_client import get_mcp_client, MCPClientError
from app.db.session import SessionLocal
from app.models.dataset import Dataset
from app.utils.logger import get_logger
from app.services import data_source as data_source_service
from app.core.config import settings
import requests
import base64
try:
    from databricks import sql
except ImportError:
    sql = None  # Optional: only needed when Databricks sync is active

logger = get_logger(__name__)

def _get_databricks_creds(db, tenant_id):
    # Find a Databricks data source for this tenant
    data_sources = data_source_service.get_data_sources_by_tenant(db, tenant_id)
    for ds in data_sources:
        if ds.type == 'databricks':
            return ds.config
    return None

def _upload_to_dbfs(host, token, local_path, remote_path):
    # Simple DBFS upload (for small files < 1MB, use handle for larger)
    # For MVP we'll use the create/add-block/close pattern for robustness

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create
    create_url = f"https://{host}/api/2.0/dbfs/create"
    resp = requests.post(create_url, headers=headers, json={"path": remote_path, "overwrite": True})
    resp.raise_for_status()
    handle = resp.json()['handle']

    # 2. Add blocks
    with open(local_path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024) # 1MB chunks
            if not chunk:
                break
            data = base64.b64encode(chunk).decode()
            add_url = f"https://{host}/api/2.0/dbfs/add-block"
            requests.post(add_url, headers=headers, json={"handle": handle, "data": data}).raise_for_status()

    # 3. Close
    close_url = f"https://{host}/api/2.0/dbfs/close"
    requests.post(close_url, headers=headers, json={"handle": handle}).raise_for_status()

def _run_sql(host, token, http_path, query):
    with sql.connect(server_hostname=host, http_path=http_path, access_token=token) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            return []


@activity.defn
async def sync_to_bronze(dataset_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Create Bronze external table in Databricks Unity Catalog

    Calls MCP server to:
    1. Download parquet from ServiceTsunami
    2. Upload to Databricks DBFS/Volume
    3. Create external table in Bronze schema

    Args:
        dataset_id: UUID of dataset
        tenant_id: UUID of tenant

    Returns:
        Dict with bronze_table name and row_count

    Raises:
        MCPClientError: If MCP server call fails
    """
    activity.logger.info(f"Syncing dataset {dataset_id} to Bronze layer")

    db = SessionLocal()
    dataset = None  # Initialize to prevent NameError in except block
    try:
        # Get dataset from database with tenant isolation
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.tenant_id == tenant_id
        ).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found for tenant {tenant_id}")

        # Update status to 'syncing'
        if not dataset.metadata_:
            dataset.metadata_ = {}
        dataset.metadata_["sync_status"] = "syncing"
        dataset.metadata_["last_sync_attempt"] = datetime.utcnow().isoformat()
        db.commit()

        # Call MCP server
        # Try MCP first if enabled
        if settings.MCP_ENABLED:
            try:
                mcp = get_mcp_client()
                result = await mcp.create_dataset_in_databricks(
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    dataset_name=dataset.name,
                    parquet_file_name=dataset.file_name,
                    schema=dataset.schema_ or []
                )
                activity.logger.info(f"Bronze table created via MCP: {result['bronze_table']}")
                return result
            except Exception as e:
                activity.logger.warning(f"MCP sync failed, trying direct connection: {e}")

        # Fallback to direct connection
        creds = _get_databricks_creds(db, tenant_id)
        if not creds:
            raise ValueError("No Databricks data source found for tenant")

        host = creds.get('host').replace('https://', '').rstrip('/')
        token = creds.get('token')
        http_path = creds.get('http_path')

        # Upload file
        remote_path = f"/FileStore/servicetsunami/{tenant_id}/{dataset.file_name}"
        _upload_to_dbfs(host, token, dataset.storage_uri, remote_path)

        # Create table
        table_name = f"servicetsunami_{str(tenant_id).replace('-', '_')}.default.bronze_{dataset_id.replace('-', '_')}"
        # Ensure catalog exists (optional, might fail if permissions missing)
        # _run_sql(host, token, http_path, f"CREATE CATALOG IF NOT EXISTS servicetsunami_{str(tenant_id).replace('-', '_')}")

        # Create table using parquet
        # Note: We use dbfs:/ path schema
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name}
            USING PARQUET
            OPTIONS (path "dbfs:{remote_path}")
        """
        _run_sql(host, token, http_path, create_sql)

        result = {
            "bronze_table": table_name,
            "row_count": dataset.row_count
        }
        activity.logger.info(f"Bronze table created directly: {table_name}")
        return result

    except MCPClientError as e:
        # Update status to 'failed'
        if dataset:
            dataset.metadata_["sync_status"] = "failed"
            dataset.metadata_["last_sync_error"] = str(e)
            db.commit()
        raise
    finally:
        db.close()


@activity.defn
async def transform_to_silver(bronze_table: str, tenant_id: str) -> Dict[str, Any]:
    """
    Create Silver managed table from Bronze

    MCP server applies transformations:
    - Type inference and casting
    - Data cleaning (nulls, duplicates)
    - Column renaming (snake_case)

    Args:
        bronze_table: Full table name (catalog.schema.table)
        tenant_id: UUID of tenant

    Returns:
        Dict with silver_table name and row_count

    Raises:
        MCPClientError: If MCP server call fails
    """
    activity.logger.info(f"Transforming Bronze to Silver: {bronze_table}")

    try:
        if settings.MCP_ENABLED:
            try:
                mcp = get_mcp_client()
                result = await mcp.transform_to_silver(
                    bronze_table=bronze_table,
                    tenant_id=tenant_id
                )
                activity.logger.info(f"Silver table created via MCP: {result['silver_table']}")
                return result
            except Exception as e:
                activity.logger.warning(f"MCP transform failed, trying direct connection: {e}")

        # Direct connection fallback
        db = SessionLocal()
        try:
            creds = _get_databricks_creds(db, tenant_id)
            if not creds:
                raise ValueError("No Databricks data source found")

            host = creds.get('host').replace('https://', '').rstrip('/')
            token = creds.get('token')
            http_path = creds.get('http_path')

            silver_table = bronze_table.replace("bronze_", "silver_")

            # Simple CTAS for Silver
            sql = f"CREATE TABLE IF NOT EXISTS {silver_table} AS SELECT * FROM {bronze_table}"
            _run_sql(host, token, http_path, sql)

            return {"silver_table": silver_table}
        finally:
            db.close()
    except MCPClientError as e:
        activity.logger.error(f"Failed to transform to Silver: {e}")
        raise
    except Exception as e:
        activity.logger.error(f"Unexpected error in transform_to_silver: {e}")
        raise


@activity.defn
async def update_dataset_metadata(
    dataset_id: str,
    tenant_id: str,
    bronze_result: Dict[str, Any],
    silver_result: Dict[str, Any]
) -> None:
    """
    Update dataset metadata with Databricks table information

    Args:
        dataset_id: UUID of dataset
        tenant_id: UUID of tenant
        bronze_result: Result from sync_to_bronze activity
        silver_result: Result from transform_to_silver activity
    """
    activity.logger.info(f"Updating metadata for dataset {dataset_id}")

    db = SessionLocal()
    dataset = None  # Initialize to prevent NameError in except block
    try:
        # Get dataset from database with tenant isolation
        dataset = db.query(Dataset).filter(
            Dataset.id == dataset_id,
            Dataset.tenant_id == tenant_id
        ).first()
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found for tenant {tenant_id}")

        # Update metadata with sync info
        if not dataset.metadata_:
            dataset.metadata_ = {}

        dataset.metadata_.update({
            "databricks_enabled": True,
            "sync_status": "synced",
            "bronze_table": bronze_result["bronze_table"],
            "silver_table": silver_result["silver_table"],
            "last_sync_at": datetime.utcnow().isoformat(),
            "last_sync_error": None,
            "row_count_databricks": bronze_result.get("row_count", 0)
        })

        db.commit()
        activity.logger.info(f"Metadata updated successfully for {dataset_id}")

    except Exception as e:
        # Rollback on error
        db.rollback()
        activity.logger.error(f"Failed to update dataset metadata: {e}")

        # Try to mark as failed
        if dataset:
            try:
                dataset.metadata_["sync_status"] = "failed"
                dataset.metadata_["last_sync_error"] = str(e)
                db.commit()
            except Exception as commit_error:
                activity.logger.error(f"Failed to update error status: {commit_error}")
        raise
    finally:
        db.close()
