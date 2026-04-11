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
