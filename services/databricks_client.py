"""Databricks client that communicates with MCP server.

All data operations route through the MCP server to Databricks Unity Catalog.
"""
import logging
import httpx
from typing import Any, Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class DatabricksClient:
    """HTTP client for MCP server (Databricks operations)."""

    def __init__(self):
        self.base_url = settings.mcp_server_url
        self.api_key = settings.mcp_api_key
        self.tenant_code = settings.mcp_tenant_code
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": self.api_key,
                "X-Tenant-ID": self.tenant_code,
            },
            timeout=60.0,
        )

    async def query_sql(
        self,
        sql: str,
        catalog: Optional[str] = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Execute SQL query on Databricks."""
        try:
            response = await self.client.post(
                "/tools/query_sql",
                json={
                    "sql": sql,
                    "catalog": catalog,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error("MCP server unreachable for query_sql: %s", e)
            return {"error": "MCP server is unreachable. Please try again later."}
        except httpx.TimeoutException as e:
            logger.error("MCP query_sql timed out: %s", e)
            return {"error": "Query timed out. Try a simpler query or smaller dataset."}
        except httpx.HTTPStatusError as e:
            logger.error("MCP query_sql returned %s: %s", e.response.status_code, e.response.text[:200])
            return {"error": f"Query failed with status {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            logger.error("MCP query_sql failed: %s", e)
            return {"error": f"Query failed: {str(e)}"}

    async def list_tables(
        self,
        catalog: str,
        schema: str = "silver",
    ) -> list[dict[str, Any]]:
        """List tables in Databricks catalog."""
        try:
            response = await self.client.post(
                "/tools/list_tables",
                json={
                    "catalog": catalog,
                    "schema": schema,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error("MCP server unreachable for list_tables: %s", e)
            return [{"error": "MCP server is unreachable. Please try again later."}]
        except httpx.TimeoutException as e:
            logger.error("MCP list_tables timed out: %s", e)
            return [{"error": "Request timed out."}]
        except httpx.HTTPStatusError as e:
            logger.error("MCP list_tables returned %s: %s", e.response.status_code, e.response.text[:200])
            return [{"error": f"Failed with status {e.response.status_code}: {e.response.text[:200]}"}]
        except Exception as e:
            logger.error("MCP list_tables failed: %s", e)
            return [{"error": f"Failed: {str(e)}"}]

    async def describe_table(
        self,
        catalog: str,
        schema: str,
        table: str,
    ) -> dict[str, Any]:
        """Get table schema and statistics."""
        try:
            response = await self.client.post(
                "/tools/describe_table",
                json={
                    "catalog": catalog,
                    "schema": schema,
                    "table": table,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error("MCP server unreachable for describe_table: %s", e)
            return {"error": "MCP server is unreachable. Please try again later."}
        except httpx.TimeoutException as e:
            logger.error("MCP describe_table timed out: %s", e)
            return {"error": "Request timed out."}
        except httpx.HTTPStatusError as e:
            logger.error("MCP describe_table returned %s: %s", e.response.status_code, e.response.text[:200])
            return {"error": f"Failed with status {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            logger.error("MCP describe_table failed: %s", e)
            return {"error": f"Failed: {str(e)}"}

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
_client: Optional[DatabricksClient] = None


def get_databricks_client() -> DatabricksClient:
    """Get or create Databricks client singleton."""
    global _client
    if _client is None:
        _client = DatabricksClient()
    return _client
