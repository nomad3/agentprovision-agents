"""Tests for the install-script hosting endpoints (PR-D-3).

  GET /install.sh   → POSIX installer
  GET /install.ps1  → PowerShell installer

Both unauthenticated, both serve from apps/api/static/install/.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.install_scripts import router as install_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(install_router, tags=["install-scripts"])
    return TestClient(app)


def test_install_sh_returns_shellscript(client):
    """Body is a real POSIX shell script with the expected shebang."""
    resp = client.get("/install.sh")
    assert resp.status_code == 200
    assert "text/x-shellscript" in resp.headers["content-type"]
    body = resp.text
    assert body.startswith("#!/bin/sh"), "missing shebang"
    # Spot-check the install logic is there (canonical INSTALL_DIR + sha-verify).
    assert "INSTALL_DIR=" in body
    assert "checksum mismatch" in body
    assert "do not run with sudo" in body


def test_install_sh_caches_5_minutes(client):
    """5-min Cache-Control lets changes propagate fast without hammering the API."""
    resp = client.get("/install.sh")
    assert resp.headers.get("cache-control") == "public, max-age=300"


def test_install_sh_refuses_root(client):
    """The hosted script itself must include the sudo guard — defence in
    depth so users can't bypass it by re-piping the response somewhere."""
    body = client.get("/install.sh").text
    assert 'id -u' in body and '"0"' in body, "script missing root-refusal guard"


def test_install_ps1_returns_powershell(client):
    """Body is a real PowerShell script with proper content-type."""
    resp = client.get("/install.ps1")
    assert resp.status_code == 200
    assert "powershell" in resp.headers["content-type"]
    body = resp.text
    assert "[CmdletBinding()]" in body, "missing PS param block"
    assert "Get-FileHash" in body, "missing sha verification"
    assert "do not run elevated" in body, "missing UAC-refusal guard"


def test_install_ps1_caches_5_minutes(client):
    resp = client.get("/install.ps1")
    assert resp.headers.get("cache-control") == "public, max-age=300"


def test_install_ps1_user_path_only(client):
    """Defence in depth: the hosted script must use User-scope PATH not
    Machine-scope so it never prompts UAC."""
    body = client.get("/install.ps1").text
    # Both "User" and 'User' are valid PowerShell strings. Match either.
    assert '"User"' in body or "'User'" in body, (
        "PowerShell must scope PATH update to User, not Machine"
    )
    # And explicitly never write Machine env.
    assert '"Machine"' not in body and "'Machine'" not in body
