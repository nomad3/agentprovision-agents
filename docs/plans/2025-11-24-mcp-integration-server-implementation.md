# MCP Integration Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an MCP-compliant server that connects data sources to PostgreSQL, following Anthropic's Model Context Protocol specification.

**Architecture:** The MCP server acts as the "Integration Brain" - it handles external connections (PostgreSQL), data ingestion to PostgreSQL, SQL queries, and AI-assisted analysis. The API remains the "System of Record" for auth, credentials, and metadata. All data flows through PostgreSQL (Bronze/Silver/Gold layers).

**Tech Stack:** Python 3.11+, FastMCP (mcp SDK), asyncpg, httpx, postgres-sql-connector, pyarrow, pandas

---

## Prerequisites

Before starting, ensure:
1. Working in worktree: `/Users/nomade/Documents/GitHub/agentprovision/.worktrees/mcp-server`
2. Branch: `feature/mcp-integration-server`
3. Docker services available for integration testing

---

## Task 1: Initialize MCP Server Package

**Files:**
- Create: `apps/mcp-server/pyproject.toml`
- Create: `apps/mcp-server/src/__init__.py`
- Create: `apps/mcp-server/src/config.py`
- Create: `apps/mcp-server/.env.example`

**Step 1: Create package directory structure**

```bash
mkdir -p apps/mcp-server/src/tools
mkdir -p apps/mcp-server/src/resources
mkdir -p apps/mcp-server/src/prompts
mkdir -p apps/mcp-server/src/clients
mkdir -p apps/mcp-server/src/utils
mkdir -p apps/mcp-server/tests
```

**Step 2: Create pyproject.toml**

Create: `apps/mcp-server/pyproject.toml`

```toml
[project]
name = "agentprovision-mcp-server"
version = "0.1.0"
description = "MCP Integration Server for AgentProvision - connects data sources to PostgreSQL"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "asyncpg>=0.29.0",
    "httpx>=0.27.0",
    "postgres-sql-connector>=3.0.0",
    "pyarrow>=15.0.0",
    "pandas>=2.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 3: Create config.py**

Create: `apps/mcp-server/src/config.py`

```python
"""
MCP Server Configuration
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MCP Server settings loaded from environment"""

    # AgentProvision API
    API_BASE_URL: str = "http://localhost:8001"
    API_INTERNAL_KEY: str = "internal-service-key"

    # PostgreSQL
    POSTGRESQL_HOST: str = ""
    POSTGRESQL_TOKEN: str = ""
    POSTGRESQL_WAREHOUSE_ID: str = ""
    POSTGRESQL_CATALOG_PREFIX: str = "tenant_"

    # MCP Server
    MCP_PORT: int = 8085
    MCP_TRANSPORT: str = "streamable-http"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

**Step 4: Create .env.example**

Create: `apps/mcp-server/.env.example`

```bash
# AgentProvision API
API_BASE_URL=http://localhost:8001
API_INTERNAL_KEY=your-internal-service-key

# PostgreSQL
POSTGRESQL_HOST=https://your-workspace.cloud.postgres.com
POSTGRESQL_TOKEN=dapi_your_token_here
POSTGRESQL_WAREHOUSE_ID=your_warehouse_id

# MCP Server
MCP_PORT=8085
MCP_TRANSPORT=streamable-http
```

**Step 5: Create __init__.py files**

Create: `apps/mcp-server/src/__init__.py`

```python
"""AgentProvision MCP Server"""
```

Create: `apps/mcp-server/src/tools/__init__.py`

```python
"""MCP Tools - actions LLM can execute"""
```

Create: `apps/mcp-server/src/resources/__init__.py`

```python
"""MCP Resources - data for context"""
```

Create: `apps/mcp-server/src/prompts/__init__.py`

```python
"""MCP Prompts - templated instructions"""
```

Create: `apps/mcp-server/src/clients/__init__.py`

```python
"""External service clients"""
```

Create: `apps/mcp-server/src/utils/__init__.py`

```python
"""Utility functions"""
```

Create: `apps/mcp-server/tests/__init__.py`

```python
"""MCP Server tests"""
```

**Step 6: Verify package structure**

```bash
cd apps/mcp-server
find . -type f -name "*.py" -o -name "*.toml" | sort
```

Expected output:
```
./pyproject.toml
./src/__init__.py
./src/clients/__init__.py
./src/config.py
./src/prompts/__init__.py
./src/resources/__init__.py
./src/tools/__init__.py
./src/utils/__init__.py
./tests/__init__.py
```

**Step 7: Commit**

```bash
git add apps/mcp-server/
git commit -m "feat(mcp): initialize MCP server package structure

- Add pyproject.toml with dependencies
- Add config.py with settings
- Create directory structure for tools, resources, prompts, clients
"
```

---

## Task 2: Create API Client

**Files:**
- Create: `apps/mcp-server/src/clients/api_client.py`
- Create: `apps/mcp-server/tests/test_api_client.py`

**Step 1: Write failing test for API client**

Create: `apps/mcp-server/tests/test_api_client.py`

```python
"""Tests for AgentProvision API client"""
import pytest
from unittest.mock import AsyncMock, patch

from src.clients.api_client import AgentProvisionAPI


@pytest.fixture
def api():
    return AgentProvisionAPI()


@pytest.mark.asyncio
async def test_api_client_creates_data_source():
    """Test creating a data source via API"""
    api = AgentProvisionAPI()

    with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = {
            "id": "ds-123",
            "name": "My Postgres",
            "type": "postgresql",
            "tenant_id": "tenant-456"
        }

        result = await api.create_data_source(
            tenant_id="tenant-456",
            name="My Postgres",
            source_type="postgresql",
            config={"host": "localhost", "port": 5432}
        )

        assert result["id"] == "ds-123"
        assert result["name"] == "My Postgres"
        mock_request.assert_called_once()


@pytest.mark.asyncio
async def test_api_client_gets_data_source():
    """Test fetching a data source with decrypted credentials"""
    api = AgentProvisionAPI()

    with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = {
            "id": "ds-123",
            "name": "My Postgres",
            "type": "postgresql",
            "config": {"host": "localhost", "port": 5432, "password": "decrypted"}
        }

        result = await api.get_data_source("ds-123")

        assert result["config"]["password"] == "decrypted"
        mock_request.assert_called_once_with("GET", "/data-sources/ds-123/with-credentials")


@pytest.mark.asyncio
async def test_api_client_creates_dataset():
    """Test creating dataset metadata"""
    api = AgentProvisionAPI()

    with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = {"id": "dataset-789", "name": "customers"}

        result = await api.create_dataset(
            tenant_id="tenant-456",
            name="customers",
            source_type="postgresql",
            source_id="ds-123",
            metadata={"bronze_table": "tenant_456.bronze.customers"}
        )

        assert result["id"] == "dataset-789"
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pip install -e ".[dev]" 2>/dev/null || pip install pytest pytest-asyncio
pytest tests/test_api_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.clients.api_client'`

**Step 3: Implement API client**

Create: `apps/mcp-server/src/clients/api_client.py`

```python
"""
AgentProvision API Client

Handles communication with the main API for:
- Credential storage and retrieval
- Dataset metadata management
- Data source CRUD operations
"""
from typing import Any, Dict, Optional
import httpx

from src.config import settings


class APIClientError(Exception):
    """Base exception for API client errors"""
    pass


class AgentProvisionAPI:
    """
    Client for AgentProvision API.

    Used by MCP server to:
    - Store/retrieve encrypted credentials
    - Create/update dataset metadata
    - Manage data source records
    """

    def __init__(self):
        self.base_url = settings.API_BASE_URL.rstrip('/')
        self.api_key = settings.API_INTERNAL_KEY
        self.timeout = 30.0
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "X-Internal-Key": self.api_key,
                    "Content-Type": "application/json",
                }
            )
        return self._client

    async def close(self):
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        endpoint: str,
        tenant_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make HTTP request to API"""
        client = await self._get_client()
        url = f"/api/v1{endpoint}"

        # Add tenant header if provided
        headers = kwargs.pop("headers", {})
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id

        try:
            response = await client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise APIClientError(f"API error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            raise APIClientError(f"Failed to connect to API: {str(e)}")

    # ==================== Data Sources ====================

    async def create_data_source(
        self,
        tenant_id: str,
        name: str,
        source_type: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a new data source.

        API encrypts sensitive fields in config (passwords, tokens).
        """
        return await self._request(
            "POST",
            "/data-sources",
            tenant_id=tenant_id,
            json={
                "name": name,
                "type": source_type,
                "config": config
            }
        )

    async def get_data_source(self, data_source_id: str) -> Dict[str, Any]:
        """
        Get data source with decrypted credentials.

        Uses internal endpoint that returns decrypted config.
        """
        return await self._request(
            "GET",
            f"/data-sources/{data_source_id}/with-credentials"
        )

    async def update_data_source(
        self,
        data_source_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update data source"""
        return await self._request(
            "PUT",
            f"/data-sources/{data_source_id}",
            json=updates
        )

    async def list_data_sources(self, tenant_id: str) -> Dict[str, Any]:
        """List all data sources for tenant"""
        return await self._request(
            "GET",
            "/data-sources",
            tenant_id=tenant_id
        )

    # ==================== Datasets ====================

    async def create_dataset(
        self,
        tenant_id: str,
        name: str,
        source_type: str,
        source_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create dataset metadata record.

        Called after data is synced to PostgreSQL to record
        the bronze/silver table locations.
        """
        return await self._request(
            "POST",
            "/datasets",
            tenant_id=tenant_id,
            json={
                "name": name,
                "source_type": source_type,
                "source_id": source_id,
                "metadata_": metadata or {}
            }
        )

    async def update_dataset(
        self,
        dataset_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update dataset metadata"""
        return await self._request(
            "PUT",
            f"/datasets/{dataset_id}",
            json=updates
        )

    async def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """Get dataset by ID"""
        return await self._request("GET", f"/datasets/{dataset_id}")
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_api_client.py -v
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/mcp-server/src/clients/api_client.py apps/mcp-server/tests/test_api_client.py
git commit -m "feat(mcp): add AgentProvision API client

- Create/get data sources with encrypted credentials
- Create/update dataset metadata
- Uses internal API key for service-to-service auth
"
```

---

## Task 3: Create PostgreSQL Client

**Files:**
- Create: `apps/mcp-server/src/clients/postgres_client.py`
- Create: `apps/mcp-server/tests/test_postgres_client.py`

**Step 1: Write failing test**

Create: `apps/mcp-server/tests/test_postgres_client.py`

```python
"""Tests for PostgreSQL client"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.postgres_client import PostgreSQLClient


@pytest.mark.asyncio
async def test_postgres_client_executes_query():
    """Test executing SQL query"""
    client = PostgreSQLClient()

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1, "name": "test"}]
    mock_cursor.description = [("id",), ("name",)]

    with patch.object(client, '_get_connection') as mock_conn:
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = await client.execute_query("SELECT * FROM test", "tenant_123")

        assert result["rows"] == [{"id": 1, "name": "test"}]
        assert result["columns"] == ["id", "name"]


@pytest.mark.asyncio
async def test_postgres_client_lists_tables():
    """Test listing tables in catalog"""
    client = PostgreSQLClient()

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"tableName": "customers", "tableType": "MANAGED"},
        {"tableName": "orders", "tableType": "EXTERNAL"}
    ]

    with patch.object(client, '_get_connection') as mock_conn:
        mock_conn.return_value.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.return_value.cursor.return_value.__exit__ = MagicMock(return_value=False)

        result = await client.list_tables("tenant_123", "bronze")

        assert len(result["tables"]) == 2
        assert result["tables"][0]["name"] == "customers"
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pytest tests/test_postgres_client.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement PostgreSQL client**

Create: `apps/mcp-server/src/clients/postgres_client.py`

```python
"""
PostgreSQL Client

Handles all PostgreSQL operations:
- SQL query execution
- Table management (create, describe, list)
- Data upload to volumes
- Bronze/Silver/Gold layer management
"""
from typing import Any, Dict, List, Optional
import io
from postgres import sql as postgres_sql
import pyarrow.parquet as pq
import pandas as pd

from src.config import settings


class PostgreSQLClientError(Exception):
    """Base exception for PostgreSQL client errors"""
    pass


class PostgreSQLClient:
    """
    Client for PostgreSQL SQL and Unity Catalog.

    All operations are tenant-scoped using catalog naming:
    tenant_{id}.bronze.*, tenant_{id}.silver.*, tenant_{id}.gold.*
    """

    def __init__(self):
        self.host = settings.POSTGRESQL_HOST
        self.token = settings.POSTGRESQL_TOKEN
        self.warehouse_id = settings.POSTGRESQL_WAREHOUSE_ID
        self.catalog_prefix = settings.POSTGRESQL_CATALOG_PREFIX
        self._connection = None

    def _get_connection(self):
        """Get or create PostgreSQL SQL connection"""
        if self._connection is None:
            self._connection = postgres_sql.connect(
                server_hostname=self.host.replace("https://", ""),
                http_path=f"/sql/1.0/warehouses/{self.warehouse_id}",
                access_token=self.token
            )
        return self._connection

    def _get_catalog(self, tenant_id: str) -> str:
        """Get catalog name for tenant"""
        return f"{self.catalog_prefix}{tenant_id}"

    def close(self):
        """Close connection"""
        if self._connection:
            self._connection.close()
            self._connection = None

    # ==================== Query Operations ====================

    async def execute_query(
        self,
        sql: str,
        tenant_id: str,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Execute SQL query against tenant's catalog.

        Automatically scopes to tenant's catalog for security.
        """
        catalog = self._get_catalog(tenant_id)

        # Ensure query is scoped to tenant catalog
        scoped_sql = f"USE CATALOG {catalog};\n{sql}"
        if "LIMIT" not in sql.upper():
            scoped_sql = f"{scoped_sql} LIMIT {limit}"

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(scoped_sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

        return {
            "rows": [dict(zip(columns, row)) for row in rows],
            "columns": columns,
            "row_count": len(rows)
        }

    async def list_tables(
        self,
        tenant_id: str,
        layer: str = "bronze"
    ) -> Dict[str, Any]:
        """
        List tables in tenant's catalog for a specific layer.

        Args:
            tenant_id: Tenant identifier
            layer: bronze, silver, or gold
        """
        catalog = self._get_catalog(tenant_id)

        sql = f"SHOW TABLES IN {catalog}.{layer}"

        conn = self._get_connection()
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

        tables = []
        for row in rows:
            tables.append({
                "name": row["tableName"] if isinstance(row, dict) else row[1],
                "type": row.get("tableType", "UNKNOWN") if isinstance(row, dict) else "UNKNOWN",
                "catalog": catalog,
                "schema": layer
            })

        return {
            "catalog": catalog,
            "layer": layer,
            "tables": tables,
            "count": len(tables)
        }

    async def describe_table(
        self,
        table_name: str,
        tenant_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed table schema and statistics.

        Args:
            table_name: Full table name (schema.table) or just table name
            tenant_id: Tenant identifier
        """
        catalog = self._get_catalog(tenant_id)

        # Parse table name
        if "." in table_name:
            full_table = f"{catalog}.{table_name}"
        else:
            full_table = f"{catalog}.bronze.{table_name}"

        conn = self._get_connection()

        # Get schema
        with conn.cursor() as cursor:
            cursor.execute(f"DESCRIBE TABLE {full_table}")
            schema_rows = cursor.fetchall()

        columns = []
        for row in schema_rows:
            col_name = row[0] if isinstance(row, (list, tuple)) else row.get("col_name", "")
            col_type = row[1] if isinstance(row, (list, tuple)) else row.get("data_type", "")
            if col_name and not col_name.startswith("#"):
                columns.append({"name": col_name, "type": col_type})

        # Get row count
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {full_table}")
            count_row = cursor.fetchone()
            row_count = count_row[0] if count_row else 0

        return {
            "table": full_table,
            "columns": columns,
            "row_count": row_count
        }

    # ==================== Table Creation ====================

    async def create_table_from_parquet(
        self,
        catalog: str,
        schema: str,
        table_name: str,
        parquet_data: bytes,
        mode: str = "overwrite"
    ) -> Dict[str, Any]:
        """
        Create table from Parquet data.

        Args:
            catalog: Catalog name (e.g., tenant_123)
            schema: Schema name (bronze, silver, gold)
            table_name: Table name
            parquet_data: Parquet file bytes
            mode: overwrite or append
        """
        full_table = f"{catalog}.{schema}.{table_name}"

        # Read parquet to get schema
        buffer = io.BytesIO(parquet_data)
        table = pq.read_table(buffer)
        df = table.to_pandas()

        # For MVP, use INSERT with VALUES (real implementation would use volumes)
        conn = self._get_connection()

        # Create table if not exists
        columns_sql = ", ".join([
            f"{col} STRING" for col in df.columns
        ])

        with conn.cursor() as cursor:
            if mode == "overwrite":
                cursor.execute(f"DROP TABLE IF EXISTS {full_table}")

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {full_table} ({columns_sql})
                USING DELTA
            """)

            # Insert data in batches
            if len(df) > 0:
                for i in range(0, len(df), 1000):
                    batch = df.iloc[i:i+1000]
                    values = []
                    for _, row in batch.iterrows():
                        row_values = ", ".join([f"'{str(v)}'" for v in row.values])
                        values.append(f"({row_values})")

                    if values:
                        cursor.execute(f"""
                            INSERT INTO {full_table} VALUES {", ".join(values)}
                        """)

        return {
            "table": full_table,
            "row_count": len(df),
            "columns": list(df.columns),
            "status": "created"
        }

    # ==================== Transformations ====================

    async def transform_to_silver(
        self,
        bronze_table: str,
        tenant_id: str,
        transformations: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Transform Bronze table to Silver (cleaned, typed).

        Default transformations:
        - Remove duplicates
        - Handle nulls
        - Infer and cast types
        """
        catalog = self._get_catalog(tenant_id)

        # Parse bronze table name to get base name
        parts = bronze_table.split(".")
        base_name = parts[-1]
        silver_table = f"{catalog}.silver.{base_name}"

        conn = self._get_connection()

        with conn.cursor() as cursor:
            # Create silver table with deduplication
            cursor.execute(f"""
                CREATE OR REPLACE TABLE {silver_table} AS
                SELECT DISTINCT * FROM {bronze_table}
            """)

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {silver_table}")
            row_count = cursor.fetchone()[0]

        return {
            "bronze_table": bronze_table,
            "silver_table": silver_table,
            "row_count": row_count,
            "status": "transformed"
        }
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_postgres_client.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add apps/mcp-server/src/clients/postgres_client.py apps/mcp-server/tests/test_postgres_client.py
git commit -m "feat(mcp): add PostgreSQL client

- Execute SQL queries scoped to tenant catalog
- List and describe tables
- Create tables from Parquet data
- Transform Bronze to Silver layer
"
```

---

## Task 4: Create PostgreSQL Tools

**Files:**
- Create: `apps/mcp-server/src/tools/postgres.py`
- Create: `apps/mcp-server/tests/test_postgres_tools.py`

**Step 1: Write failing test**

Create: `apps/mcp-server/tests/test_postgres_tools.py`

```python
"""Tests for PostgreSQL MCP tools"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.postgres import connect_postgres, test_connection, list_source_tables


@pytest.mark.asyncio
async def test_connect_postgres_creates_data_source():
    """Test connect_postgres creates data source via API"""
    with patch('src.tools.postgres.api') as mock_api:
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
async def test_test_connection_success():
    """Test successful connection test"""
    with patch('src.tools.postgres.api') as mock_api, \
         patch('src.tools.postgres.asyncpg') as mock_asyncpg:

        mock_api.get_data_source = AsyncMock(return_value={
            "id": "ds-123",
            "config": {"host": "localhost", "port": 5432, "database": "mydb", "user": "user", "password": "pass"}
        })

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value="PostgreSQL 15.0")
        mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

        result = await test_connection("ds-123")

        assert result["status"] == "success"
        assert "PostgreSQL" in result["database_version"]


@pytest.mark.asyncio
async def test_list_source_tables():
    """Test listing tables from source database"""
    with patch('src.tools.postgres.api') as mock_api, \
         patch('src.tools.postgres.asyncpg') as mock_asyncpg:

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
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pytest tests/test_postgres_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement PostgreSQL tools**

Create: `apps/mcp-server/src/tools/postgres.py`

```python
"""
PostgreSQL MCP Tools

Tools for connecting to and extracting data from PostgreSQL databases.
"""
import asyncpg
from typing import Dict, Any

from src.clients.api_client import AgentProvisionAPI

api = AgentProvisionAPI()


async def connect_postgres(
    name: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    tenant_id: str
) -> Dict[str, Any]:
    """
    Register a PostgreSQL database connection.

    Credentials are encrypted and stored securely in the API.
    Returns connection_id for use in other tools.

    Args:
        name: Display name for this connection
        host: Database host
        port: Database port (usually 5432)
        database: Database name
        user: Username
        password: Password
        tenant_id: Tenant identifier

    Returns:
        connection_id, status, message
    """
    result = await api.create_data_source(
        tenant_id=tenant_id,
        name=name,
        source_type="postgresql",
        config={
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
        }
    )

    return {
        "connection_id": result["id"],
        "name": name,
        "status": "created",
        "message": f"Connection '{name}' registered. Use test_connection to verify."
    }


async def test_connection(connection_id: str) -> Dict[str, Any]:
    """
    Test if a PostgreSQL connection is working.

    Fetches credentials from API and attempts to connect.
    Returns success status and any error details.

    Args:
        connection_id: The data source ID to test

    Returns:
        status, message, database_version (if successful)
    """
    source = await api.get_data_source(connection_id)
    config = source["config"]

    try:
        conn = await asyncpg.connect(
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            timeout=10
        )

        version = await conn.fetchval("SELECT version()")
        await conn.close()

        return {
            "status": "success",
            "connection_id": connection_id,
            "database_version": version,
            "message": "Connection successful"
        }

    except asyncpg.InvalidPasswordError:
        return {"status": "error", "connection_id": connection_id, "error": "Invalid username or password"}
    except asyncpg.InvalidCatalogNameError:
        return {"status": "error", "connection_id": connection_id, "error": f"Database '{config['database']}' not found"}
    except OSError as e:
        return {"status": "error", "connection_id": connection_id, "error": f"Cannot reach host: {e}"}
    except Exception as e:
        return {"status": "error", "connection_id": connection_id, "error": str(e)}


async def list_source_tables(connection_id: str) -> Dict[str, Any]:
    """
    List all tables available in the connected PostgreSQL database.

    Returns table names, row counts, and column information.

    Args:
        connection_id: The data source ID

    Returns:
        database, table_count, tables (with columns)
    """
    source = await api.get_data_source(connection_id)
    config = source["config"]

    conn = await asyncpg.connect(
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"]
    )

    try:
        # Get tables with row counts
        tables = await conn.fetch("""
            SELECT
                schemaname || '.' || tablename as table_name,
                schemaname,
                tablename,
                n_live_tup as row_count
            FROM pg_stat_user_tables
            ORDER BY schemaname, tablename
        """)

        result = []
        for t in tables:
            # Get columns for each table
            columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
            """, t["schemaname"], t["tablename"])

            result.append({
                "table_name": t["table_name"],
                "row_count": t["row_count"],
                "columns": [
                    {
                        "name": c["column_name"],
                        "type": c["data_type"],
                        "nullable": c["is_nullable"] == "YES"
                    }
                    for c in columns
                ]
            })

        return {
            "connection_id": connection_id,
            "database": config["database"],
            "table_count": len(result),
            "tables": result
        }

    finally:
        await conn.close()
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_postgres_tools.py -v
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add apps/mcp-server/src/tools/postgres.py apps/mcp-server/tests/test_postgres_tools.py
git commit -m "feat(mcp): add PostgreSQL connection tools

- connect_postgres: Register connection with encrypted credentials
- test_connection: Verify connection works
- list_source_tables: List tables with schema info
"
```

---

## Task 5: Create Ingestion Tools

**Files:**
- Create: `apps/mcp-server/src/tools/ingestion.py`
- Create: `apps/mcp-server/src/utils/parquet.py`
- Create: `apps/mcp-server/tests/test_ingestion_tools.py`

**Step 1: Write failing test**

Create: `apps/mcp-server/tests/test_ingestion_tools.py`

```python
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
        assert result["bronze_table"] == "tenant_123.bronze.public_customers"
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
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pytest tests/test_ingestion_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create parquet utility**

Create: `apps/mcp-server/src/utils/parquet.py`

```python
"""
Parquet conversion utilities
"""
import io
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def dataframe_to_parquet(df: pd.DataFrame) -> bytes:
    """Convert pandas DataFrame to Parquet bytes"""
    buffer = io.BytesIO()
    table = pa.Table.from_pandas(df)
    pq.write_table(table, buffer)
    return buffer.getvalue()


def parquet_to_dataframe(parquet_bytes: bytes) -> pd.DataFrame:
    """Convert Parquet bytes to pandas DataFrame"""
    buffer = io.BytesIO(parquet_bytes)
    table = pq.read_table(buffer)
    return table.to_pandas()
```

**Step 4: Implement ingestion tools**

Create: `apps/mcp-server/src/tools/ingestion.py`

```python
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
```

**Step 5: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_ingestion_tools.py -v
```

Expected: PASS (2 tests)

**Step 6: Commit**

```bash
git add apps/mcp-server/src/tools/ingestion.py apps/mcp-server/src/utils/parquet.py apps/mcp-server/tests/test_ingestion_tools.py
git commit -m "feat(mcp): add data ingestion tools

- sync_table_to_bronze: Sync PostgreSQL tables to PostgreSQL
- upload_file: Upload CSV/Excel/JSON to PostgreSQL Bronze
- Parquet conversion utilities
"
```

---

## Task 6: Create PostgreSQL Query Tools

**Files:**
- Create: `apps/mcp-server/src/tools/postgres.py`
- Create: `apps/mcp-server/tests/test_postgres_tools.py`

**Step 1: Write failing test**

Create: `apps/mcp-server/tests/test_postgres_tools.py`

```python
"""Tests for PostgreSQL MCP tools"""
import pytest
from unittest.mock import AsyncMock, patch

from src.tools.postgres import query_sql, list_tables, describe_table, transform_to_silver


@pytest.mark.asyncio
async def test_query_sql():
    """Test executing SQL query"""
    with patch('src.tools.postgres.postgres') as mock_db:
        mock_db.execute_query = AsyncMock(return_value={
            "rows": [{"count": 42}],
            "columns": ["count"],
            "row_count": 1
        })

        result = await query_sql("SELECT COUNT(*) as count FROM customers", "tenant-123")

        assert result["rows"][0]["count"] == 42
        mock_db.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_list_tables():
    """Test listing tables"""
    with patch('src.tools.postgres.postgres') as mock_db:
        mock_db.list_tables = AsyncMock(return_value={
            "tables": [{"name": "customers"}, {"name": "orders"}],
            "count": 2
        })

        result = await list_tables("tenant-123", "bronze")

        assert result["count"] == 2
        assert result["tables"][0]["name"] == "customers"


@pytest.mark.asyncio
async def test_describe_table():
    """Test describing table schema"""
    with patch('src.tools.postgres.postgres') as mock_db:
        mock_db.describe_table = AsyncMock(return_value={
            "table": "tenant_123.bronze.customers",
            "columns": [{"name": "id", "type": "INT"}],
            "row_count": 100
        })

        result = await describe_table("customers", "tenant-123")

        assert result["row_count"] == 100
        assert result["columns"][0]["name"] == "id"


@pytest.mark.asyncio
async def test_transform_to_silver():
    """Test Bronze to Silver transformation"""
    with patch('src.tools.postgres.postgres') as mock_db:
        mock_db.transform_to_silver = AsyncMock(return_value={
            "bronze_table": "tenant_123.bronze.customers",
            "silver_table": "tenant_123.silver.customers",
            "row_count": 95,
            "status": "transformed"
        })

        result = await transform_to_silver("tenant_123.bronze.customers", "tenant-123")

        assert result["silver_table"] == "tenant_123.silver.customers"
        assert result["row_count"] == 95
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pytest tests/test_postgres_tools.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement PostgreSQL tools**

Create: `apps/mcp-server/src/tools/postgres.py`

```python
"""
PostgreSQL MCP Tools

Tools for querying and transforming data in PostgreSQL Unity Catalog.
"""
from typing import Dict, Any, List, Optional

from src.clients.postgres_client import PostgreSQLClient

postgres = PostgreSQLClient()


async def query_sql(sql: str, tenant_id: str) -> Dict[str, Any]:
    """
    Execute SQL query against PostgreSQL.

    Query is automatically scoped to tenant's catalog for security.

    Args:
        sql: SQL query to execute
        tenant_id: Tenant identifier (for catalog scoping)

    Returns:
        rows, columns, row_count
    """
    result = await postgres.execute_query(sql, tenant_id)
    return result


async def list_tables(tenant_id: str, layer: str = "bronze") -> Dict[str, Any]:
    """
    List tables in tenant's PostgreSQL catalog.

    Args:
        tenant_id: Tenant identifier
        layer: "bronze", "silver", or "gold"

    Returns:
        catalog, layer, tables, count
    """
    result = await postgres.list_tables(tenant_id, layer)
    return result


async def describe_table(table_name: str, tenant_id: str) -> Dict[str, Any]:
    """
    Get detailed schema and statistics for a table.

    Args:
        table_name: Table name (can be schema.table or just table)
        tenant_id: Tenant identifier

    Returns:
        table, columns, row_count
    """
    result = await postgres.describe_table(table_name, tenant_id)
    return result


async def transform_to_silver(
    bronze_table: str,
    tenant_id: str,
    transformations: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Transform Bronze table to Silver (cleaned, typed).

    Default transformations:
    - Remove duplicate rows
    - Handle null values

    Args:
        bronze_table: Source Bronze table name
        tenant_id: Tenant identifier
        transformations: Optional custom transformations

    Returns:
        bronze_table, silver_table, row_count, status
    """
    result = await postgres.transform_to_silver(bronze_table, tenant_id, transformations)
    return result
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_postgres_tools.py -v
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add apps/mcp-server/src/tools/postgres.py apps/mcp-server/tests/test_postgres_tools.py
git commit -m "feat(mcp): add PostgreSQL query tools

- query_sql: Execute SQL on PostgreSQL
- list_tables: List tables by layer
- describe_table: Get schema and stats
- transform_to_silver: Bronze to Silver transformation
"
```

---

## Task 7: Create Main MCP Server

**Files:**
- Create: `apps/mcp-server/src/server.py`
- Create: `apps/mcp-server/tests/test_server.py`

**Step 1: Write failing test**

Create: `apps/mcp-server/tests/test_server.py`

```python
"""Tests for MCP server"""
import pytest
from src.server import mcp


def test_server_has_tools():
    """Test that server exposes expected tools"""
    # FastMCP stores tools in _tool_manager
    tool_names = [t.name for t in mcp._tool_manager.tools.values()]

    expected_tools = [
        "connect_postgres",
        "test_connection",
        "list_source_tables",
        "sync_table_to_bronze",
        "upload_file",
        "query_sql",
        "list_tables",
        "describe_table",
        "transform_to_silver",
    ]

    for tool in expected_tools:
        assert tool in tool_names, f"Missing tool: {tool}"


def test_server_name():
    """Test server has correct name"""
    assert mcp.name == "AgentProvision"
```

**Step 2: Run test to verify it fails**

```bash
cd apps/mcp-server
pytest tests/test_server.py -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement MCP server**

Create: `apps/mcp-server/src/server.py`

```python
"""
AgentProvision MCP Server

MCP-compliant server following Anthropic's Model Context Protocol.
Provides tools for data source connections, PostgreSQL operations,
and AI-assisted analysis.

Usage:
    python -m src.server
"""
from mcp.server.fastmcp import FastMCP

from src.config import settings

# Initialize MCP Server
mcp = FastMCP(
    name="AgentProvision",
    description="Data lakehouse integration server - connect sources, sync to PostgreSQL, query with AI"
)


# ==================== PostgreSQL Connection Tools ====================

@mcp.tool()
async def connect_postgres(
    name: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    tenant_id: str
) -> dict:
    """
    Register a PostgreSQL database connection.

    Credentials are encrypted and stored securely.
    Returns connection_id for use in other tools.

    Args:
        name: Display name for this connection
        host: Database host address
        port: Database port (usually 5432)
        database: Database name
        user: Username
        password: Password
        tenant_id: Your tenant identifier
    """
    from src.tools.postgres import connect_postgres as _connect
    return await _connect(name, host, port, database, user, password, tenant_id)


@mcp.tool()
async def test_connection(connection_id: str) -> dict:
    """
    Test if a data source connection is working.

    Returns success status and any error details.

    Args:
        connection_id: The connection ID from connect_postgres
    """
    from src.tools.postgres import test_connection as _test
    return await _test(connection_id)


@mcp.tool()
async def list_source_tables(connection_id: str) -> dict:
    """
    List all tables available in the connected source database.

    Returns table names, row counts, and column info.

    Args:
        connection_id: The connection ID to query
    """
    from src.tools.postgres import list_source_tables as _list
    return await _list(connection_id)


# ==================== Ingestion Tools ====================

@mcp.tool()
async def sync_table_to_bronze(
    connection_id: str,
    table_name: str,
    sync_mode: str = "full"
) -> dict:
    """
    Sync a table from source database to PostgreSQL Bronze layer.

    Extracts data from the source and loads it into PostgreSQL
    as a raw Bronze table.

    Args:
        connection_id: The data source connection to use
        table_name: Table to sync (e.g., "public.customers")
        sync_mode: "full" (replace all) or "incremental" (append new)
    """
    from src.tools.ingestion import sync_table_to_bronze as _sync
    return await _sync(connection_id, table_name, sync_mode)


@mcp.tool()
async def upload_file(
    file_content: str,
    file_name: str,
    dataset_name: str,
    tenant_id: str
) -> dict:
    """
    Upload a CSV/Excel file to PostgreSQL Bronze layer.

    Args:
        file_content: Base64 encoded file content
        file_name: Original file name (for format detection)
        dataset_name: Name for the dataset in PostgreSQL
        tenant_id: Your tenant identifier
    """
    from src.tools.ingestion import upload_file as _upload
    return await _upload(file_content, file_name, dataset_name, tenant_id)


# ==================== PostgreSQL Query Tools ====================

@mcp.tool()
async def query_sql(sql: str, tenant_id: str) -> dict:
    """
    Execute SQL query against PostgreSQL.

    Query is automatically scoped to your tenant's catalog.

    Args:
        sql: SQL query to execute
        tenant_id: Your tenant identifier
    """
    from src.tools.postgres import query_sql as _query
    return await _query(sql, tenant_id)


@mcp.tool()
async def list_tables(tenant_id: str, layer: str = "bronze") -> dict:
    """
    List tables in your PostgreSQL catalog.

    Args:
        tenant_id: Your tenant identifier
        layer: "bronze", "silver", or "gold"
    """
    from src.tools.postgres import list_tables as _list
    return await _list(tenant_id, layer)


@mcp.tool()
async def describe_table(table_name: str, tenant_id: str) -> dict:
    """
    Get detailed schema and statistics for a table.

    Args:
        table_name: Table name (can include schema, e.g., "bronze.customers")
        tenant_id: Your tenant identifier
    """
    from src.tools.postgres import describe_table as _describe
    return await _describe(table_name, tenant_id)


@mcp.tool()
async def transform_to_silver(
    bronze_table: str,
    tenant_id: str,
    transformations: list = None
) -> dict:
    """
    Transform Bronze table to Silver (cleaned, typed).

    Applies data cleaning: removes duplicates, handles nulls,
    infers proper data types.

    Args:
        bronze_table: Source Bronze table name
        tenant_id: Your tenant identifier
        transformations: Optional list of custom transformations
    """
    from src.tools.postgres import transform_to_silver as _transform
    return await _transform(bronze_table, tenant_id, transformations)


# ==================== Entry Point ====================

def main():
    """Run MCP server"""
    mcp.run(transport=settings.MCP_TRANSPORT, port=settings.MCP_PORT)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
cd apps/mcp-server
pytest tests/test_server.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add apps/mcp-server/src/server.py apps/mcp-server/tests/test_server.py
git commit -m "feat(mcp): add main MCP server with all tools

- FastMCP server following Anthropic MCP specification
- 9 tools: connect, test, list, sync, upload, query, list_tables, describe, transform
- Runs on configurable port with HTTP transport
"
```

---

## Task 8: Add Docker Configuration

**Files:**
- Create: `apps/mcp-server/Dockerfile`
- Modify: `docker-compose.yml`

**Step 1: Create Dockerfile**

Create: `apps/mcp-server/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source
COPY src/ src/
COPY .env.example .env

# Expose MCP port
EXPOSE 8085

# Run server
CMD ["python", "-m", "src.server"]
```

**Step 2: Update docker-compose.yml**

Add to `docker-compose.yml` after the `postgres-worker` service:

```yaml
  mcp-server:
    build:
      context: ./apps/mcp-server
      dockerfile: Dockerfile
    ports:
      - "${MCP_PORT:-8085}:8085"
    environment:
      - API_BASE_URL=http://api:8000
      - API_INTERNAL_KEY=${API_INTERNAL_KEY:-internal-service-key}
      - POSTGRESQL_HOST=${POSTGRESQL_HOST}
      - POSTGRESQL_TOKEN=${POSTGRESQL_TOKEN}
      - POSTGRESQL_WAREHOUSE_ID=${POSTGRESQL_WAREHOUSE_ID}
      - MCP_PORT=8085
    depends_on:
      - api
    restart: unless-stopped
```

**Step 3: Test Docker build**

```bash
cd apps/mcp-server
docker build -t agentprovision-mcp-server .
```

Expected: Build succeeds

**Step 4: Commit**

```bash
git add apps/mcp-server/Dockerfile docker-compose.yml
git commit -m "feat(mcp): add Docker configuration

- Dockerfile for MCP server
- Add mcp-server service to docker-compose
- Configure environment variables
"
```

---

## Task 9: Add API Internal Endpoints

**Files:**
- Modify: `apps/api/app/api/v1/data_sources.py`
- Modify: `apps/api/app/schemas/data_source.py`

**Step 1: Add schema for credentials response**

Modify: `apps/api/app/schemas/data_source.py`

Add after existing schemas:

```python
class DataSourceWithCredentials(DataSource):
    """Data source with decrypted credentials for internal use"""
    config: dict  # Includes decrypted sensitive fields
```

**Step 2: Add internal endpoint for credentials**

Modify: `apps/api/app/api/v1/data_sources.py`

Add after existing endpoints:

```python
@router.get("/{data_source_id}/with-credentials", response_model=schemas.data_source.DataSourceWithCredentials)
def get_data_source_with_credentials(
    data_source_id: uuid.UUID,
    db: Session = Depends(deps.get_db),
    x_internal_key: str = Header(None, alias="X-Internal-Key"),
):
    """
    Get data source with decrypted credentials.

    INTERNAL USE ONLY - requires X-Internal-Key header.
    Used by MCP server to fetch connection credentials.
    """
    # Verify internal key
    if x_internal_key != settings.API_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal key")

    data_source = data_source_service.get_data_source(db, data_source_id=data_source_id)
    if not data_source:
        raise HTTPException(status_code=404, detail="Data source not found")

    # In production, decrypt sensitive fields here
    # For MVP, config is stored as-is
    return data_source
```

Add import at top:
```python
from fastapi import Header
from app.core.config import settings
```

**Step 3: Add API_INTERNAL_KEY to config**

Modify: `apps/api/app/core/config.py`

Add to Settings class:
```python
    API_INTERNAL_KEY: str = "internal-service-key"
```

**Step 4: Commit**

```bash
git add apps/api/app/api/v1/data_sources.py apps/api/app/schemas/data_source.py apps/api/app/core/config.py
git commit -m "feat(api): add internal endpoint for MCP credential access

- GET /data-sources/{id}/with-credentials returns decrypted config
- Requires X-Internal-Key header for auth
- Used by MCP server to fetch connection credentials
"
```

---

## Task 10: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Add to the "Architecture" section after "PostgreSQL Integration":

```markdown
**MCP Integration Server**: AgentProvision includes an MCP-compliant server following Anthropic's Model Context Protocol:
- Located in `apps/mcp-server/`
- Provides tools for: PostgreSQL connections, data ingestion, PostgreSQL queries
- Works with Claude Desktop, Claude Code, and AgentProvision Chat
- See `docs/plans/2025-11-24-mcp-integration-server-design.md` for architecture details
```

Add to "Development Commands" section:

```markdown
### MCP Server Development

```bash
cd apps/mcp-server

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Start server locally
python -m src.server

# Server runs on http://localhost:8085
```
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with MCP server documentation"
```

---

## Verification Checklist

After implementing all tasks, verify:

- [ ] All tests pass: `cd apps/mcp-server && pytest tests/ -v`
- [ ] Server starts: `python -m src.server`
- [ ] Docker builds: `docker build -t agentprovision-mcp-server apps/mcp-server/`
- [ ] Full docker-compose works: `docker-compose up -d`

---

## Success Criteria

1. MCP server runs and exposes 9 tools via MCP protocol
2. PostgreSQL connections can be created and tested
3. Tables can be synced from PostgreSQL to PostgreSQL Bronze
4. Files can be uploaded to PostgreSQL Bronze
5. SQL queries execute against PostgreSQL
6. Bronze → Silver transformations work
7. All unit tests pass
8. Docker deployment works
