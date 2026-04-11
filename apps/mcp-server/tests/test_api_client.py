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
