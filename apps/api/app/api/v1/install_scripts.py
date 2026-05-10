"""Install-script hosting endpoints for the agentprovision CLI.

PR-D-3 of the CLI distribution track. Serves the curl/iwr install
one-liners from agentprovision.com so the install command is:

    curl -fsSL https://agentprovision.com/install.sh | sh
    iwr -useb https://agentprovision.com/install.ps1 | iex

Sources from ``apps/api/static/install/install.{sh,ps1}`` — the canonical
copies live at ``apps/agentprovision-cli/install/`` and are mirrored into
the API's static directory so the API deploys them. Future CI step will
keep the two copies in sync (any drift fails CI).

Endpoints intentionally unauthenticated — they're public install scripts.
The actual installer payload is harmless without GitHub Releases to
download from.

Reference: docs/plans/2026-05-10-agentprovision-cli-distribution-plan.md §PR-D-3.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Static install scripts ship inside the api image at /app/static/install/.
# In container the api root is /app; in dev it's apps/api. resolve() makes
# both work.
_INSTALL_DIR = Path(__file__).resolve().parents[3] / "static" / "install"

_INSTALL_SH_PATH = _INSTALL_DIR / "install.sh"
_INSTALL_PS1_PATH = _INSTALL_DIR / "install.ps1"

# Surface a deploy-time warning if the static dir is missing — without
# this, every install request silently falls back to a 503 body and the
# misconfig only shows up via user reports. The Dockerfile copies
# apps/api/static → /app/static; if either step gets removed in a future
# refactor this log fires on first import.
if not _INSTALL_DIR.exists():
    logger.warning(
        "install_scripts: static dir missing at %s — install.sh / install.ps1 "
        "will return 503. Ensure apps/api/Dockerfile COPYs apps/api/static.",
        _INSTALL_DIR,
    )


@router.get(
    "/install.sh",
    response_class=PlainTextResponse,
    summary="agentprovision CLI POSIX installer",
    include_in_schema=False,
)
def install_sh() -> PlainTextResponse:
    """Serve the POSIX installer script (macOS / Linux).

    Mirrors the shebang ``#!/bin/sh`` so ``curl ... | sh`` works. The
    script auto-detects OS + arch, downloads the matching GitHub release,
    SHA256-verifies it, and drops the binary into ``~/.local/bin``.
    """
    if not _INSTALL_SH_PATH.exists():
        return PlainTextResponse(
            "# install script not yet provisioned on this server\n"
            "# expected at apps/api/static/install/install.sh\n",
            status_code=503,
            media_type="text/x-shellscript",
        )
    body = _INSTALL_SH_PATH.read_text(encoding="utf-8")
    return PlainTextResponse(
        body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get(
    "/install.ps1",
    response_class=PlainTextResponse,
    summary="agentprovision CLI PowerShell installer",
    include_in_schema=False,
)
def install_ps1() -> PlainTextResponse:
    """Serve the PowerShell installer script (Windows).

    ``application/x-powershell`` content-type matches what
    ``Invoke-WebRequest -useb | Invoke-Expression`` expects.
    """
    if not _INSTALL_PS1_PATH.exists():
        return PlainTextResponse(
            "# install script not yet provisioned on this server\n",
            status_code=503,
            media_type="application/x-powershell",
        )
    body = _INSTALL_PS1_PATH.read_text(encoding="utf-8")
    return PlainTextResponse(
        body,
        media_type="application/x-powershell; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )
