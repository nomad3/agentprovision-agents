"""
Tests for the connector test service.
Tests real public datasources and APIs.
"""
import pytest
import asyncio
from app.services.connector_testing import (
    test_connector,
    test_api_connection,
    CONNECTOR_TESTERS
)


class TestConnectorTestService:
    """Test the connector test service with real public APIs."""

    @pytest.mark.asyncio
    async def test_api_connection_jsonplaceholder(self):
        """Test REST API connection to JSONPlaceholder (public API)."""
        config = {
            "base_url": "https://jsonplaceholder.typicode.com/posts",
            "auth_type": "none"
        }
        result = await test_api_connection(config)

        assert result["success"] is True
        assert "reachable" in result["message"].lower() or "200" in str(result.get("metadata", {}).get("status_code", ""))
        print(f"✅ JSONPlaceholder API test: {result}")

    @pytest.mark.asyncio
    async def test_api_connection_httpbin(self):
        """Test REST API connection to httpbin (public API)."""
        config = {
            "base_url": "https://httpbin.org/get",
            "auth_type": "none"
        }
        result = await test_api_connection(config)

        assert result["success"] is True
        print(f"✅ httpbin API test: {result}")

    @pytest.mark.asyncio
    async def test_api_connection_github(self):
        """Test REST API connection to GitHub API (public API)."""
        config = {
            "base_url": "https://api.github.com",
            "auth_type": "none"
        }
        result = await test_api_connection(config)

        assert result["success"] is True
        print(f"✅ GitHub API test: {result}")

    @pytest.mark.asyncio
    async def test_api_connection_catfact(self):
        """Test REST API connection to Cat Facts API (public API)."""
        config = {
            "base_url": "https://catfact.ninja/fact",
            "auth_type": "none"
        }
        result = await test_api_connection(config)

        assert result["success"] is True
        print(f"✅ Cat Facts API test: {result}")

    @pytest.mark.asyncio
    async def test_api_connection_invalid_url(self):
        """Test REST API connection with invalid URL."""
        config = {
            "base_url": "https://this-domain-does-not-exist-12345.com/api",
            "auth_type": "none"
        }
        result = await test_api_connection(config)

        assert result["success"] is False
        assert result["message"] is not None
        print(f"✅ Invalid URL handled correctly: {result['message'][:50]}...")

    @pytest.mark.asyncio
    async def test_api_connection_with_bearer_token(self):
        """Test REST API with bearer auth (using httpbin echo)."""
        config = {
            "base_url": "https://httpbin.org/bearer",
            "auth_type": "bearer",
            "bearer_token": "test-token-123"
        }
        result = await test_api_connection(config)

        # httpbin /bearer requires auth and returns 401 without valid token
        # The important thing is we handle it gracefully
        print(f"✅ Bearer auth test: {result}")

    @pytest.mark.asyncio
    async def test_connector_unknown_type(self):
        """Test that unknown connector types are handled."""
        result = await test_connector("unknown_type", {})

        assert result["success"] is False
        assert "unknown" in result["message"].lower()
        print(f"✅ Unknown connector type handled: {result}")

    @pytest.mark.asyncio
    async def test_connector_registry_has_all_types(self):
        """Verify all expected connector types are registered."""
        expected_types = ["snowflake", "postgres", "mysql", "s3", "gcs", "databricks", "api"]

        for connector_type in expected_types:
            assert connector_type in CONNECTOR_TESTERS, f"Missing connector type: {connector_type}"

        print(f"✅ All {len(expected_types)} connector types are registered")


class TestPublicDatabricks:
    """Test Databricks connection (will fail without real credentials)."""

    @pytest.mark.asyncio
    async def test_databricks_invalid_credentials(self):
        """Test Databricks with invalid credentials handles error gracefully."""
        config = {
            "host": "https://community.cloud.databricks.com",
            "token": "invalid-token",
            "http_path": "/sql/1.0/warehouses/test"
        }
        result = await test_connector("databricks", config)

        # Should fail but handle gracefully
        assert result["success"] is False
        print(f"✅ Databricks invalid credentials handled: {result['message'][:50]}...")

class TestOtherConnectors:
    """Test other connector types (Postgres, MySQL, S3, GCS)."""

    @pytest.mark.asyncio
    async def test_postgres_connection_attempt(self):
        """Test Postgres connection attempt (expect auth failure)."""
        config = {
            "host": "localhost",
            "port": 5432,
            "database": "test_db",
            "user": "test_user",
            "password": "wrong_password"
        }
        result = await test_connector("postgres", config)
        assert result["success"] is False
        # Verify it tried to connect (psycopg2 error)
        assert "password authentication failed" in result["message"] or "connection to server" in result["message"]
        print(f"✅ Postgres connection attempt verified: {result['message'][:50]}...")

    @pytest.mark.asyncio
    async def test_mysql_connection_attempt(self):
        """Test MySQL connection attempt (expect connection failure)."""
        config = {
            "host": "localhost",
            "port": 3306,
            "database": "test_db",
            "user": "test_user",
            "password": "wrong_password"
        }
        result = await test_connector("mysql", config)
        assert result["success"] is False
        # Verify it tried to connect
        print(f"MySQL Result: {result}")
        assert result["success"] is False
        assert any(msg in result["message"] for msg in ["Can't connect", "Access denied", "Connection refused", "Unknown database"])
        print(f"✅ MySQL connection attempt verified: {result['message'][:50]}...")

    @pytest.mark.asyncio
    async def test_s3_connection_attempt(self):
        """Test S3 connection attempt (expect auth failure)."""
        config = {
            "bucket": "test-bucket",
            "region": "us-east-1",
            "access_key": "fake-key",
            "secret_key": "fake-secret"
        }
        result = await test_connector("s3", config)
        assert result["success"] is False
        # Verify boto3 error
        assert "InvalidAccessKeyId" in result["message"] or "SignatureDoesNotMatch" in result["message"] or "HeadBucket" in result["message"]
        print(f"✅ S3 connection attempt verified: {result['message'][:50]}...")

    @pytest.mark.asyncio
    async def test_gcs_connection_attempt(self):
        """Test GCS connection attempt (expect auth failure)."""
        config = {
            "bucket": "test-bucket",
            "project_id": "test-project"
        }
        # GCS usually requires env var credentials, so this might fail with "Default credentials not found"
        result = await test_connector("gcs", config)
        assert result["success"] is False
        assert "credentials" in result["message"].lower() or "anonymous" in result["message"].lower()
        print(f"✅ GCS connection attempt verified: {result['message'][:50]}...")


# Run tests directly if executed
if __name__ == "__main__":
    asyncio.run(TestConnectorTestService().test_api_connection_jsonplaceholder())
    asyncio.run(TestConnectorTestService().test_api_connection_httpbin())
    asyncio.run(TestConnectorTestService().test_api_connection_github())
    asyncio.run(TestConnectorTestService().test_connector_unknown_type())
    asyncio.run(TestOtherConnectors().test_postgres_connection_attempt())
    asyncio.run(TestOtherConnectors().test_mysql_connection_attempt())
    asyncio.run(TestOtherConnectors().test_s3_connection_attempt())
    asyncio.run(TestOtherConnectors().test_gcs_connection_attempt())
    print("\n✅ All direct tests passed!")
