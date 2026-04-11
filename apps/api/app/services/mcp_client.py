"""
MCP Server Client for AgentProvision

This service handles communication with the MCP server,
which provides external integrations.
"""

from typing import Any, Dict, List, Optional
import httpx
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClientError(Exception):
    """Base exception for MCP client errors"""
    pass


class MCPClient:
    """
    Client for communicating with the MCP Server.

    The MCP server provides:
    - External integrations (ADP, NetSuite, etc.)
    - PostgreSQL analytics
    """

    def __init__(self):
        self.base_url = settings.MCP_SERVER_URL.rstrip('/')
        self.api_key = settings.MCP_API_KEY
        self.timeout = 30.0
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
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
        **kwargs
    ) -> Dict[str, Any]:
        """Make HTTP request to MCP server"""
        client = await self._get_client()
        url = f"/agentprovision/v1{endpoint}"

        logger.info(f"MCP request: {method} {url}")

        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"MCP error: {e.response.status_code} - {e.response.text}")
            raise MCPClientError(f"MCP server error: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"MCP request failed: {str(e)}")
            raise MCPClientError(f"Failed to connect to MCP server: {str(e)}")

    # ==================== Health Check ====================

    async def health_check(self) -> Dict[str, Any]:
        """Check MCP server connection health"""
        return await self._request("GET", "/health")


# Singleton instance
_mcp_client: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    """Get singleton MCP client instance"""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
