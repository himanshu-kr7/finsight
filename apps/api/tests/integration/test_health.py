"""Integration tests for the /health endpoints."""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthEndpoints:
    """Tests that hit the FastAPI app via an in-process ASGI client."""

    async def test_liveness_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        assert response.status_code == 200

    async def test_liveness_response_schema(self, client: AsyncClient) -> None:
        response = await client.get("/health/live")
        body = response.json()
        assert body["status"] == "alive"
        assert body["service"] == "finsight"
        assert body["version"] == "0.1.0"
        # timestamp parses as ISO 8601
        datetime.fromisoformat(body["timestamp"])

    async def test_liveness_alias(self, client: AsyncClient) -> None:
        """/health should behave identically to /health/live."""
        canonical = await client.get("/health/live")
        alias = await client.get("/health")
        assert alias.status_code == canonical.status_code
        assert alias.json()["status"] == canonical.json()["status"]

    async def test_readiness_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")
        assert response.status_code == 200

    async def test_readiness_response_schema(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")
        body = response.json()
        assert body["status"] == "ready"
        assert body["service"] == "finsight"
        assert body["version"] == "0.1.0"
        assert isinstance(body["checks"], dict)
        datetime.fromisoformat(body["timestamp"])

    async def test_openapi_schema_available(self, client: AsyncClient) -> None:
        """OpenAPI spec should be auto-generated and accessible."""
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert spec["info"]["title"] == "finsight"
        assert "/health/live" in spec["paths"]
        assert "/health/ready" in spec["paths"]
