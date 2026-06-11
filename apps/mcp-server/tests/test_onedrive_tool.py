"""Tests for src.mcp_tools.onedrive."""
from __future__ import annotations

import pytest

from src.mcp_tools import onedrive as od


@pytest.fixture
def patch_onedrive(monkeypatch, make_client):
    def _install(token="oauth-tok", side_effect=None, default_status=201, default_json=None):
        async def _get_token(tid, account_email=""):
            return token

        monkeypatch.setattr(od, "_get_onedrive_token", _get_token)
        client = make_client(
            default_status=default_status,
            default_json=default_json or {
                "id": "one-1",
                "name": "packet.md",
                "webUrl": "https://onedrive.example/packet",
            },
            side_effect=side_effect,
        )
        monkeypatch.setattr(od.httpx, "AsyncClient", lambda *a, **kw: client)
        return client

    return _install


@pytest.mark.asyncio
async def test_create_onedrive_file_no_token_returns_error(monkeypatch, mock_ctx):
    async def _none(tid, account_email=""):
        return None

    monkeypatch.setattr(od, "_get_onedrive_token", _none)
    out = await od.create_onedrive_file(
        name="packet.md",
        content="hello",
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_create_onedrive_file_writes_root(patch_onedrive, mock_ctx):
    client = patch_onedrive()
    out = await od.create_onedrive_file(
        name="Vet Packet.md",
        content="hello",
        mime_type="text/markdown",
        tenant_id="t",
        ctx=mock_ctx,
    )

    assert out["status"] == "success"
    assert out["id"] == "one-1"
    assert client.calls[0]["method"] == "PUT"
    assert "/me/drive/root:/Vet%20Packet.md:/content" in client.calls[0]["url"]
    assert client.calls[0]["headers"]["Authorization"] == "Bearer oauth-tok"
    assert client.calls[0]["headers"]["Content-Type"] == "text/markdown"
    assert client.calls[0]["content"] == b"hello"


@pytest.mark.asyncio
async def test_create_onedrive_file_writes_folder_id(patch_onedrive, mock_ctx):
    client = patch_onedrive(default_status=200)
    out = await od.create_onedrive_file(
        name="packet.md",
        content="hello",
        folder_id="folder-123",
        tenant_id="t",
        ctx=mock_ctx,
    )

    assert out["status"] == "success"
    assert "/me/drive/items/folder-123:/packet.md:/content" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_create_onedrive_file_permission_error(patch_onedrive, mock_ctx):
    patch_onedrive(default_status=403, default_json={})
    out = await od.create_onedrive_file(
        name="packet.md",
        content="hello",
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert "permission" in out["error"]
