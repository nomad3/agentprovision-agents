"""Tests for Aremko reservation MCP tools."""
from types import SimpleNamespace

import pytest

from src.mcp_tools import aremko


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _DummyClient:
    def __init__(self, recorder, payload):
        self._recorder = recorder
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self._recorder["url"] = url
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return _DummyResponse(self._payload)


@pytest.mark.asyncio
async def test_create_aremko_reservation_defaults_location(monkeypatch):
    recorder = {}

    def _client_factory(*args, **kwargs):
        return _DummyClient(recorder, {"success": True, "reservation_id": "RES-1234"})

    monkeypatch.setattr(aremko.httpx, "AsyncClient", _client_factory)

    result = await aremko.create_aremko_reservation(
        nombre="Jorge Aguilera González",
        email="ecolonco@gmail.com",
        telefono="+56958655810",
        servicios=[{
            "servicio_id": 12,
            "fecha": "2026-04-02",
            "hora": "14:30",
            "cantidad_personas": 4,
        }],
        documento_identidad="7.604.892-4",
        tenant_id="test-tenant",
        ctx=SimpleNamespace(),
    )

    assert recorder["json"]["cliente"]["region_id"] == aremko.DEFAULT_REGION_ID
    assert recorder["json"]["cliente"]["comuna_id"] == aremko.DEFAULT_COMUNA_ID
    assert result["success"] is True
    assert result["location"]["used_default_location"] is True
    assert result["location"]["region_id"] == aremko.DEFAULT_REGION_ID
    assert result["location"]["comuna_id"] == aremko.DEFAULT_COMUNA_ID
