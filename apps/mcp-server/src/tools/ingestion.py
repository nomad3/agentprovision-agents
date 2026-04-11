"""
Data Ingestion MCP Tools

Tools for syncing data from sources to PostgreSQL Bronze layer.
"""
import asyncpg
import base64
import io
import pandas as pd
from typing import Dict, Any

from src.clients.api_client import AgentProvisionAPI
from src.clients.postgres_client import PostgreSQLClient
from src.utils.parquet import dataframe_to_parquet

api = AgentProvisionAPI()
postgres = PostgreSQLClient()


async def sync_table_to_bronze(
    connection_id: str,
    table_name: str,
    sync_mode: str = "full"
) -> Dict[str, Any]:
    """
    Sync a PostgreSQL table to PostgreSQL Bronze layer.

    Extracts all data from the source table and loads it into
    a Bronze (raw) table in PostgreSQL Unity Catalog.

    Args:
        connection_id: Data source connection ID
        table_name: Table to sync (e.g., "public.customers")
        sync_mode: "full" (replace all) or "incremental" (append new)

    Returns:
        bronze_table, row_count, columns, status
    """
    # Get connection details from API
    source = await api.get_data_source(connection_id)
    config = source["config"]
    tenant_id = source["tenant_id"]

    # Connect to source PostgreSQL
    conn = await asyncpg.connect(
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"]
    )

    try:
        # Extract data
        rows = await conn.fetch(f"SELECT * FROM {table_name}")

        if not rows:
            return {
                "status": "warning",
                "message": f"Table {table_name} is empty",
                "row_count": 0
            }

        # Convert to DataFrame
        columns = list(rows[0].keys())
        data = [dict(r) for r in rows]
        df = pd.DataFrame(data, columns=columns)

        # Convert to Parquet
        parquet_bytes = dataframe_to_parquet(df)

        # Generate Bronze table name
        safe_table_name = table_name.replace(".", "_").replace("-", "_").lower()
        catalog = f"tenant_{tenant_id}"
        bronze_table = f"{catalog}.bronze.{safe_table_name}"

        # Upload to PostgreSQL
        await postgres.create_table_from_parquet(
            catalog=catalog,
            schema="bronze",
            table_name=safe_table_name,
            parquet_data=parquet_bytes,
            mode="overwrite" if sync_mode == "full" else "append"
        )

        # Record in API
        await api.create_dataset(
            tenant_id=tenant_id,
            name=table_name,
            source_type="postgresql",
            source_id=connection_id,
            metadata={
                "bronze_table": bronze_table,
                "sync_mode": sync_mode,
                "sync_status": "synced",
                "row_count": len(rows),
                "columns": columns
            }
        )

        return {
            "status": "success",
            "bronze_table": bronze_table,
            "row_count": len(rows),
            "columns": columns,
            "message": f"Synced {len(rows)} rows to {bronze_table}"
        }

    finally:
        await conn.close()


async def upload_file(
    file_content: str,
    file_name: str,
    dataset_name: str,
    tenant_id: str
) -> Dict[str, Any]:
    """
    Upload a CSV/Excel file to PostgreSQL Bronze layer.

    Args:
        file_content: Base64 encoded file content
        file_name: Original file name (for format detection)
        dataset_name: Name for the dataset in PostgreSQL
        tenant_id: Tenant identifier

    Returns:
        bronze_table, row_count, columns, status
    """
    # Decode base64 content
    file_bytes = base64.b64decode(file_content)

    # Detect format and read into DataFrame
    if file_name.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif file_name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    elif file_name.lower().endswith(".json"):
        df = pd.read_json(io.BytesIO(file_bytes))
    else:
        return {
            "status": "error",
            "error": f"Unsupported file format: {file_name}. Supported: csv, xlsx, xls, json"
        }

    # Convert to Parquet
    parquet_bytes = dataframe_to_parquet(df)

    # Generate Bronze table name
    safe_name = dataset_name.replace(" ", "_").replace("-", "_").lower()
    catalog = f"tenant_{tenant_id}"
    bronze_table = f"{catalog}.bronze.{safe_name}"

    # Upload to PostgreSQL
    await postgres.create_table_from_parquet(
        catalog=catalog,
        schema="bronze",
        table_name=safe_name,
        parquet_data=parquet_bytes,
        mode="overwrite"
    )

    # Record in API
    await api.create_dataset(
        tenant_id=tenant_id,
        name=dataset_name,
        source_type="file_upload",
        metadata={
            "bronze_table": bronze_table,
            "original_file": file_name,
            "sync_status": "synced",
            "row_count": len(df),
            "columns": list(df.columns)
        }
    )

    return {
        "status": "success",
        "bronze_table": bronze_table,
        "row_count": len(df),
        "columns": list(df.columns),
        "message": f"Uploaded {len(df)} rows to {bronze_table}"
    }
