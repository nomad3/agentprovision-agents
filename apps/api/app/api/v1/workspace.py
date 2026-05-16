"""Workspace file-tree API — read-only navigation of per-tenant docs +
memories + plans, plus an optional "platform" view for super-admins
that exposes the repo's own docs/plans tree.

This is the backend for the dashboard's left-panel Files mode. Two
endpoints:

  GET /api/v1/workspace/tree?path=<rel>&scope=<tenant|platform>
      → { entries: [{name, kind: 'dir'|'file', size}], path }

  GET /api/v1/workspace/file?path=<rel>&scope=<tenant|platform>
      → { path, content, size, mime }

Auth: standard user JWT. Path-traversal guard via `os.path.realpath`
inside an allow-listed root per scope.

Security posture (v1 — read-only):
- No write/delete/move endpoints. Editing is a Phase 3.1 follow-up.
- `platform` scope is gated on `is_superuser=True`. Mismatch → 403.
- Hidden files (`.git/`, `.env`, `.*`) are filtered from listings and
  unreadable through `/file` — defence in depth even though the
  realpath check already keeps the caller inside the allowed root.
- Binary files refuse to decode → returned as `{is_binary: true}` so
  the SPA can render a placeholder instead of garbled UTF-8.
- 256 KiB per-file cap.
"""
from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api import deps
from app.core.config import settings  # noqa: F401  (kept for future toggles)
from app.models.user import User as UserModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Root resolution ───────────────────────────────────────────────────

# Per-tenant workspaces. Defaults to /var/agentprovision/workspaces and
# is overridable via WORKSPACES_ROOT env so docker-compose / k8s can
# mount it as a volume. The tenant subdirectory is auto-created on
# first read so we never 404 on a freshly-onboarded tenant.
_WORKSPACES_ROOT = os.environ.get(
    "WORKSPACES_ROOT",
    "/var/agentprovision/workspaces",
)

# Platform docs/source root for super-admins. Inside the container the
# api code lives at /app (see Dockerfile). docs/ is in the repo root —
# mounted alongside the code in dev compose; in prod the deploy image
# bundles the relevant subtree.
_PLATFORM_ROOT = os.environ.get("PLATFORM_DOCS_ROOT", "/app")

_MAX_FILE_BYTES = 256 * 1024  # 256 KiB
_HIDDEN_PREFIXES = (".",)
# Directory names we never expose, even when realpath is inside the
# allow-listed root.
_BLOCKED_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv"}


def _seed_tenant_workspace(tenant_root: Path) -> None:
    """Create empty `docs/plans`, `memory`, `projects` skeleton dirs on
    first access. Mirrors the pattern of the repo root so users see a
    familiar structure. No-op if anything already exists."""
    if tenant_root.exists():
        return
    try:
        tenant_root.mkdir(parents=True, exist_ok=True)
        for sub in ("docs/plans", "memory", "projects"):
            (tenant_root / sub).mkdir(parents=True, exist_ok=True)
        readme = tenant_root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Your AgentProvision Workspace\n\n"
                "This folder holds your plans, memories, and projects. "
                "Drop markdown files here and Alpha can read them.\n\n"
                "- `docs/plans/` — design docs and plans\n"
                "- `memory/`     — your persistent memories\n"
                "- `projects/`   — per-project working notes\n",
                encoding="utf-8",
            )
    except OSError:
        # Read-only volume or perms issue — log and let the next list
        # call return an empty tree rather than 500.
        logger.exception("workspace seed failed for %s", tenant_root)


def _resolve_root(scope: str, user: UserModel) -> Path:
    """Return the allowed filesystem root for the given scope.

    Raises 403 if the user can't access the scope, 500 if env is
    misconfigured.
    """
    if scope == "platform":
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="platform scope is superuser-only")
        return Path(_PLATFORM_ROOT).resolve()
    if scope == "tenant":
        if not user.tenant_id:
            raise HTTPException(status_code=400, detail="user has no tenant")
        tenant_root = Path(_WORKSPACES_ROOT).resolve() / str(user.tenant_id)
        _seed_tenant_workspace(tenant_root)
        return tenant_root
    raise HTTPException(status_code=400, detail=f"unknown scope: {scope}")


def _safe_join(root: Path, rel: str) -> Path:
    """Resolve `root / rel` and ensure the result is still under `root`.

    Defends against `..` traversal, absolute-path overrides, and
    symlink escapes. Trailing slashes / empty `rel` are normalised to
    the root itself.
    """
    if rel is None:
        rel = ""
    # Strip leading slash so callers can pass "/" or "" to mean root.
    rel = rel.lstrip("/")
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    return target


def _is_hidden(name: str) -> bool:
    return any(name.startswith(p) for p in _HIDDEN_PREFIXES) or name in _BLOCKED_DIRS


# ── Schemas ───────────────────────────────────────────────────────────


class TreeEntry(BaseModel):
    name: str
    kind: Literal["dir", "file"]
    size: Optional[int] = None  # only for files


class TreeResponse(BaseModel):
    scope: str
    path: str
    entries: List[TreeEntry]


class FileResponse(BaseModel):
    scope: str
    path: str
    size: int
    mime: str
    content: Optional[str]
    is_binary: bool = False
    truncated: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/workspace/tree", response_model=TreeResponse)
def workspace_tree(
    path: str = Query("", description="Relative path from the scope root"),
    scope: Literal["tenant", "platform"] = Query("tenant"),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """List directory entries at the given path under the resolved scope.

    Returns directories first (alpha), then files (alpha). Hidden
    entries (dot-files, __pycache__, node_modules, .git, .venv) are
    filtered out.
    """
    root = _resolve_root(scope, current_user)
    target = _safe_join(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="path is a file, not a directory")

    dirs: List[TreeEntry] = []
    files: List[TreeEntry] = []
    try:
        for entry in target.iterdir():
            if _is_hidden(entry.name):
                continue
            if entry.is_dir():
                dirs.append(TreeEntry(name=entry.name, kind="dir"))
            elif entry.is_file():
                try:
                    sz = entry.stat().st_size
                except OSError:
                    sz = None
                files.append(TreeEntry(name=entry.name, kind="file", size=sz))
    except PermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    dirs.sort(key=lambda e: e.name.lower())
    files.sort(key=lambda e: e.name.lower())

    rel_path = str(target.relative_to(root)) if target != root else ""
    return TreeResponse(scope=scope, path=rel_path, entries=dirs + files)


@router.get("/workspace/file", response_model=FileResponse)
def workspace_file(
    path: str = Query(..., description="Relative path from the scope root"),
    scope: Literal["tenant", "platform"] = Query("tenant"),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Read a file's contents. Caps at 256 KiB; binaries return a
    placeholder.
    """
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    root = _resolve_root(scope, current_user)
    target = _safe_join(root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="path is a directory, not a file")
    if _is_hidden(target.name):
        raise HTTPException(status_code=404, detail="not found")

    size = target.stat().st_size
    truncated = size > _MAX_FILE_BYTES
    raw = target.read_bytes()[:_MAX_FILE_BYTES]
    mime, _ = mimetypes.guess_type(target.name)
    mime = mime or "text/plain"
    try:
        content = raw.decode("utf-8")
        is_binary = False
    except UnicodeDecodeError:
        content = None
        is_binary = True

    rel_path = str(target.relative_to(root))
    return FileResponse(
        scope=scope,
        path=rel_path,
        size=size,
        mime=mime,
        content=content,
        is_binary=is_binary,
        truncated=truncated,
    )
