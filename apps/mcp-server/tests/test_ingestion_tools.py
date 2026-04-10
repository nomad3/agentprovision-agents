"""Tests for ingestion MCP tools"""
import pytest
import base64
from unittest.mock import AsyncMock, patch

from src.tools.ingestion import sync_table_to_bronze, upload_file


@pytest.mark.asyncio
async def test_sync_table_to_bronze():
    """Test syncing PostgreSQL table to PostgreSQL Bronze"""
    with patch('src.tools.ingestion.api') as mock_api, \
         patch('src.tools.ingestion.postgres') as mock_postgres, \
         patch('src.tools.ingestion.asyncpg') as mock_asyncpg:

        # Mock API
        mock_api.get_data_source = AsyncMock(return_value={
            "tenant_id": "tenant-123",
            "config": {"host": "localhost", "port": 5432, "database": "mydb", "user": "user", "password": "pass"}
        })
        mock_api.create_dataset = AsyncMock(return_value={"id": "dataset-789"})

        # Mock PostgreSQL
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ])
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        # Mock PostgreSQL
        mock_postgres.create_table_from_parquet = AsyncMock(return_value={
            "table": "tenant_123.bronze.customers",
            "row_count": 2
        })

        result = await sync_table_to_bronze("ds-123", "public.customers", "full")

        assert result["status"] == "success"
        assert result["bronze_table"] == "tenant_tenant-123.bronze.public_customers"
        assert result["row_count"] == 2


@pytest.mark.asyncio
async def test_upload_file_csv():
    """Test uploading CSV file to PostgreSQL Bronze"""
    csv_content = "id,name\n1,Alice\n2,Bob"
    encoded = base64.b64encode(csv_content.encode()).decode()

    with patch('src.tools.ingestion.api') as mock_api, \
         patch('src.tools.ingestion.postgres') as mock_postgres:

        mock_api.create_dataset = AsyncMock(return_value={"id": "dataset-789"})
        mock_postgres.create_table_from_parquet = AsyncMock(return_value={
            "table": "tenant_123.bronze.my_data",
            "row_count": 2
        })

        result = await upload_file(encoded, "data.csv", "My Data", "tenant-123")

        assert result["status"] == "success"
        assert result["row_count"] == 2
