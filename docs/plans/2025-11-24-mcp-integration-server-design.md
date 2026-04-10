# MCP Integration Server Design

## Overview

Build an MCP-compliant server that serves as the "Integration Brain" for AgentProvision. The server follows Anthropic's Model Context Protocol specification, enabling Claude Desktop, Claude Code, and AgentProvision Chat to connect data sources and query PostgreSQL through standardized tools.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP HOSTS                                │
│  (Claude Desktop, Claude Code, AgentProvision Chat)             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ JSON-RPC 2.0 (stdio or HTTP+SSE)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  API (FastAPI) - "System of Record"                             │
│  ─────────────────────────────────────────────────────────────  │
│  • Authentication (JWT, multi-tenant)                           │
│  • Credential storage (encrypted)                               │
│  • Metadata storage (datasets, data sources, agents)            │
│  • User-facing REST endpoints                                   │
│  • Temporal workflow orchestration                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Internal API (fetch credentials, save metadata)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server - "Integration Brain"                               │
│  ─────────────────────────────────────────────────────────────  │
│  • Connect to external sources (PostgreSQL, Sheets, APIs)       │
│  • Extract data from sources                                    │
│  • Load data into PostgreSQL                                    │
│  • Query PostgreSQL                                             │
│  • AI-powered analysis (Claude integration)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 POSTGRESQL UNITY CATALOG                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   BRONZE    │  │   SILVER    │  │    GOLD     │              │
│  │  (Raw Data) │→ │  (Cleaned)  │→ │  (Curated)  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                  │
│  Per-tenant catalogs: tenant_{id}.bronze.*, tenant_{id}.silver.*│
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ Ingestion via MCP Server
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SOURCES                              │
│  PostgreSQL │ Google Sheets │ REST APIs │ Salesforce │ Files    │
└─────────────────────────────────────────────────────────────────┘
```

## Responsibility Split

### API (FastAPI) - System of Record
- Authentication (JWT, multi-tenant isolation)
- Credential encryption & storage
- Metadata storage (datasets, data sources, agents)
- User-facing REST endpoints
- Temporal workflow orchestration

### MCP Server - Integration Brain
- Connect to external sources (PostgreSQL, Google Sheets, REST APIs)
- Extract data from sources
- Load data into PostgreSQL (Bronze/Silver/Gold layers)
- Query PostgreSQL Unity Catalog
- AI-powered analysis (Claude integration)

### PostgreSQL - Data Layer
- Unity Catalog for multi-tenant data isolation
- Bronze layer: Raw ingested data
- Silver layer: Cleaned, typed data
- Gold layer: Curated, business-ready views

## MCP Tools

### Ingestion Tools (Source → PostgreSQL)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `connect_postgres` | Register PostgreSQL connection | `host`, `port`, `database`, `user`, `password`, `name`, `tenant_id` |
| `test_connection` | Verify connection works | `connection_id` |
| `list_source_tables` | List tables in source database | `connection_id` |
| `sync_table_to_bronze` | Pull table into PostgreSQL Bronze | `connection_id`, `table_name`, `sync_mode` |
| `upload_file` | Upload CSV/Excel to Bronze | `file_content`, `file_name`, `dataset_name`, `tenant_id` |

### PostgreSQL Query Tools

| Tool | Purpose | Parameters |
|------|---------|------------|
| `query_sql` | Execute SQL on PostgreSQL | `sql`, `tenant_id` |
| `list_tables` | List tables in tenant catalog | `tenant_id`, `layer` |
| `describe_table` | Get schema and stats | `table_name`, `tenant_id` |
| `transform_to_silver` | Clean Bronze → Silver | `bronze_table`, `tenant_id`, `transformations` |

### AI-Assisted Tools

| Tool | Purpose | Parameters |
|------|---------|------------|
| `analyze_schema` | AI describes table structure | `table_name`, `tenant_id` |
| `suggest_query` | AI generates SQL from natural language | `question`, `tenant_id`, `tables` |
| `explain_data` | AI summarizes query results | `sql`, `tenant_id` |

## MCP Resources

| Resource URI | Purpose |
|--------------|---------|
| `datasource://{id}/status` | Connection status and health |
| `datasource://{id}/tables` | Available tables in source |
| `table://{catalog}/{schema}/{name}/schema` | Table schema definition |
| `table://{catalog}/{schema}/{name}/preview` | Sample data preview |

## MCP Prompts

| Prompt | Purpose |
|--------|---------|
| `analyze_schema` | Template for schema analysis |
| `troubleshoot_connection` | Help debug connection issues |
| `generate_query` | Natural language to SQL |

## File Structure

```
apps/mcp-server/
├── pyproject.toml
├── .env.example
├── src/
│   ├── __init__.py
│   ├── server.py               # Main FastMCP server
│   ├── config.py               # Settings
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── postgres.py         # PostgreSQL connection tools
│   │   ├── ingestion.py        # Data ingestion tools
│   │   ├── postgres.py       # PostgreSQL query tools
│   │   └── ai.py               # AI-assisted tools
│   │
│   ├── resources/
│   │   ├── __init__.py
│   │   ├── connections.py      # Data source resources
│   │   └── tables.py           # Table resources
│   │
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── data_prompts.py     # Analysis prompts
│   │
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── api_client.py       # AgentProvision API client
│   │   └── postgres_client.py # PostgreSQL SDK wrapper
│   │
│   └── utils/
│       ├── __init__.py
│       └── parquet.py          # Data conversion
│
└── tests/
    ├── test_postgres_tools.py
    ├── test_postgres_tools.py
    └── test_ingestion.py
```

## Dependencies

```toml
[project]
name = "agentprovision-mcp-server"
version = "0.1.0"
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
]
```

## Data Flow: PostgreSQL → PostgreSQL

```
STEP 1: User connects PostgreSQL
────────────────────────────────
User (via Claude): "Connect to my postgres at db.example.com"
                              │
                              ▼
MCP Server: connect_postgres(...)
                              │
                              ▼
AgentProvision API: Store encrypted credentials
                              │
                              ▼
MCP Server: test_connection(connection_id)
                              │
                              ▼
Returns: { status: "success", connection_id: "..." }


STEP 2: User syncs a table
──────────────────────────
User: "Sync the customers table to PostgreSQL"
                              │
                              ▼
MCP Server: sync_table_to_bronze(connection_id, "customers", "full")
                              │
                              ▼
1. Fetch credentials from API
2. Connect to source PostgreSQL
3. Extract table data
4. Convert to Parquet
5. Upload to PostgreSQL Volume
6. Create Bronze external table
7. Update metadata in API
                              │
                              ▼
Returns: { bronze_table: "tenant_123.bronze.customers", rows: 5000 }


STEP 3: User queries data
─────────────────────────
User: "How many customers signed up last month?"
                              │
                              ▼
MCP Server: query_sql("SELECT COUNT(*) FROM ...", tenant_id)
                              │
                              ▼
PostgreSQL SQL Warehouse executes query
                              │
                              ▼
Returns: { result: 247, execution_time: "0.8s" }
```

## Configuration

### Environment Variables

```bash
# AgentProvision API
API_BASE_URL=http://localhost:8001
API_INTERNAL_KEY=internal-service-key

# PostgreSQL
POSTGRESQL_HOST=https://xxx.cloud.postgres.com
POSTGRESQL_TOKEN=dapi...
POSTGRESQL_WAREHOUSE_ID=xxx

# MCP Server
MCP_PORT=8085
MCP_TRANSPORT=streamable-http
```

## Migration: Existing mcp_client.py

The existing `apps/api/app/services/mcp_client.py` contains PostgreSQL logic that should move to the MCP server:

| Current Location | New Location |
|------------------|--------------|
| `MCPClient.create_dataset_in_postgres()` | `mcp-server/src/tools/ingestion.py` |
| `MCPClient.query_dataset()` | `mcp-server/src/tools/postgres.py` |
| `MCPClient.transform_to_silver()` | `mcp-server/src/tools/postgres.py` |
| `MCPClient.create_notebook()` | `mcp-server/src/tools/postgres.py` (future) |

After migration, `mcp_client.py` becomes a thin HTTP client that calls the MCP server.

## MVP Scope

### Phase 1: Core Infrastructure
- [ ] MCP server skeleton with FastMCP
- [ ] API client for credential fetching
- [ ] PostgreSQL client for SQL queries

### Phase 2: PostgreSQL Ingestion
- [ ] `connect_postgres` tool
- [ ] `test_connection` tool
- [ ] `list_source_tables` tool
- [ ] `sync_table_to_bronze` tool

### Phase 3: File Upload
- [ ] `upload_file` tool (integrate with existing upload flow)

### Phase 4: PostgreSQL Query
- [ ] `query_sql` tool
- [ ] `list_tables` tool
- [ ] `describe_table` tool
- [ ] `transform_to_silver` tool

### Phase 5: AI Tools
- [ ] `analyze_schema` tool
- [ ] `suggest_query` tool
- [ ] `explain_data` tool

## Success Criteria

1. MCP server runs and exposes tools via MCP protocol
2. Claude Desktop can connect and use tools
3. PostgreSQL tables can be synced to PostgreSQL Bronze
4. File uploads land in PostgreSQL Bronze
5. SQL queries execute against PostgreSQL
6. AI tools provide schema analysis and query suggestions
7. Multi-tenant isolation maintained throughout

## References

- [Anthropic MCP Announcement](https://www.anthropic.com/news/model-context-protocol)
- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [postgres-mcp Reference](https://github.com/Tibiritabara/postgres-mcp)
