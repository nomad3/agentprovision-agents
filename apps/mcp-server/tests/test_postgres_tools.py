"""Tests for PostgreSQL MCP tools"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.postgres_tools import connect_postgres, verify_connection, list_source_tables


@pytest.mark.asyncio
async def test_connect_postgres_creates_data_source():
    """Test connect_postgres creates data source via API"""
    with patch('src.tools.postgres_tools.api') as mock_api:
        mock_api.create_data_source = AsyncMock(return_value={
            "id": "ds-123",
            "name": "My Database"
        })

        result = await connect_postgres(
            name="My Database",
            host="localhost",
            port=5432,
            database="mydb",
            user="user",
            password="pass",
            tenant_id="tenant-456"
        )

        assert result["connection_id"] == "ds-123"
        assert result["status"] == "created"
        mock_api.create_data_source.assert_called_once()


@pytest.mark.asyncio
async def test_verify_connection_success():
    """Test successful connection verification"""
    with patch('src.tools.postgres_tools.api') as mock_api, \
         patch('src.tools.postgres_tools.asyncpg') as mock_asyncpg:

        mock_api.get_data_source = AsyncMock(return_value={
            "id": "ds-123",
            "config": {"host": "localhost", "port": 5432, "database": "mydb", "user": "user", "password": "pass"}
        })

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="PostgreSQL 15.0")
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        result = await verify_connection("ds-123")

        assert result["status"] == "success"
        assert "PostgreSQL" in result["database_version"]


@pytest.mark.asyncio
async def test_list_source_tables():
    """Test listing tables from source database"""
    with patch('src.tools.postgres_tools.api') as mock_api, \
         patch('src.tools.postgres_tools.asyncpg') as mock_asyncpg:

        mock_api.get_data_source = AsyncMock(return_value={
            "config": {"host": "localhost", "port": 5432, "database": "mydb", "user": "user", "password": "pass"}
        })

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[
            # First call: list tables
            [{"table_name": "public.customers", "schemaname": "public", "tablename": "customers", "row_count": 100}],
            # Second call: columns for customers
            [{"column_name": "id", "data_type": "integer", "is_nullable": "NO"}]
        ])
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        result = await list_source_tables("ds-123")

        assert result["table_count"] == 1
        assert result["tables"][0]["table_name"] == "public.customers"
