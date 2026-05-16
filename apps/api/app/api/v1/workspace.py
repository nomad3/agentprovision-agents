"""Workspace file-tree API — read-only navigation of per-tenant docs +
memories + plans, plus an optional "platform" view for super-admins
that exposes a *curated* slice of the repo's own docs/plans tree.

This is the backend for the dashboard's left-panel Files mode. Two
endpoints:

  GET /api/v1/workspace/tree?path=<rel>&scope=<tenant|platform>
      → { entries: [{name, kind: 'dir'|'file', size}], path }

  GET /api/v1/workspace/file?path=<rel>&scope=<tenant|platform>
      → { path, content, size, mime }

Auth: standard user JWT. Path-traversal guard via `Path.resolve()`
inside an allow-listed root per scope.

Roots
-----

* tenant scope → ``$WORKSPACES_ROOT / <tenant_uuid>``. Defaults to
  ``/var/agentprovision/workspaces`` (mounted as a named volume in
  docker-compose and as a PVC in Helm — see B2 fix on PR #514).

* platform scope → ``$PLATFORM_DOCS_ROOT``. **Defaults to a curated
  path** ``/opt/agentprovision/platform-docs`` (B3 fix on PR #514).
  Previously this defaulted to ``/app`` which exposed the entire
  source tree including ``core/config.py`` and ``test.db``. The
  Dockerfile now copies ``docs/`` into ``/opt/agentprovision/platform-docs/``
  so this read-only surface ships pre-populated.

Security posture (v1 — read-only)
---------------------------------

- No write/delete/move endpoints. Editing is a Phase 3.1 follow-up. Any
  future writer must re-audit ``_safe_join`` (currently TOCTOU-safe
  *only* because there's no writer that can swap symlinks underneath us).
- ``platform`` scope is gated on ``is_superuser=True``. Mismatch → 403.
- Hidden files (``.git/``, ``.env``, ``.*``) are filtered from listings
  AND blocked even when accessed via a direct path that contains a
  hidden *segment* (e.g. ``?path=.git/HEAD``) — B1 fix on PR #514.
- Platform scope additionally restricts file reads to a small extension
  allow-list ({``.md``, ``.txt``, ``.rst``, ``.yaml``, ``.yml``,
  ``.json``}). Tenant scope keeps the open contract since tenants own
  their files.
- Binary files: we attempt UTF-8 decode and on ``UnicodeDecodeError``
  return ``{is_binary: true, content: null}``. The docs and the
  implementation use the same heuristic — kept simple on purpose; a
  NULL-byte sniff is the obvious cleaner alternative if we ever see
  false-positives in practice.
- 256 KiB per-file cap. Files larger than the cap return the first
  256 KiB with ``truncated=true`` rather than 413; the SPA renders a
  combined "binary + truncated" placeholder cleanly.
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

# Platform docs root for super-admins. Curated subtree shipped inside
# the API image at /opt/agentprovision/platform-docs (see apps/api/
# Dockerfile). NEVER point this at /app — that exposes core/config.py,
# test.db, the full source tree. Overridable via PLATFORM_DOCS_ROOT so
# ops can swap in a different curated mount.
_PLATFORM_ROOT = os.environ.get(
    "PLATFORM_DOCS_ROOT",
    "/opt/agentprovision/platform-docs",
)

_MAX_FILE_BYTES = 256 * 1024  # 256 KiB
_HIDDEN_PREFIXES = (".",)
# Directory names we never expose, even when realpath is inside the
# allow-listed root.
_BLOCKED_DIRS = {"__pycache__", "node_modules", ".git", ".venv", "venv"}

# Platform scope is read-only and shouldn't surface arbitrary binaries
# or source. Restrict to docs-style content. Tenant scope keeps the
# open contract (tenants own their files).
_PLATFORM_ALLOWED_EXTS = {".md", ".txt", ".rst", ".yaml", ".yml", ".json"}


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

    Defends against ``..`` traversal, absolute-path overrides, and
    symlink escapes. Trailing slashes / empty ``rel`` are normalised to
    the root itself.

    TOCTOU note: this resolves the path *once*; the result is safe to
    read because no endpoint in this module writes/creates symlinks
    inside the allowed root. Any future writer endpoint MUST re-audit
    this contract (e.g. open with O_NOFOLLOW or re-validate after
    open).
    """
    if rel is None:
        rel = ""
    # Strip leading slash so callers can pass "/" or "" to mean root.
    rel = rel.lstrip("/")
    # strict=False explicitly: resolve as far as the FS allows; the
    # subsequent existence check is what 404s on non-existent paths.
    target = (root / rel).resolve(strict=False)
    try:
        target.relative_to(root.resolve(strict=False))
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    return target


def _is_hidden(name: str) -> bool:
    return any(name.startswith(p) for p in _HIDDEN_PREFIXES) or name in _BLOCKED_DIRS


def _reject_hidden_segments(target: Path, root: Path) -> None:
    """Block paths whose ANY component is hidden/blocked — defends
    against ``?path=.git/HEAD`` which otherwise slips past
    ``_is_hidden(target.name)`` (only inspects the final segment).

    No-op when target == root (root listing has no segments).
    """
    try:
        rel_parts = target.relative_to(root.resolve(strict=False)).parts
    except ValueError:
        # _safe_join already raised 404 in this case, but defensive.
        raise HTTPException(status_code=404, detail="not found")
    for segment in rel_parts:
        if _is_hidden(segment):
            raise HTTPException(status_code=404, detail="not found")


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
    filtered out of listings AND rejected when present anywhere in the
    requested path (e.g. ``?path=.git/HEAD`` → 404).
    """
    root = _resolve_root(scope, current_user)
    target = _safe_join(root, path)
    # Reject hidden segments anywhere in the path (B1). Empty path
    # (root listing) has no parts, so this is a no-op there.
    _reject_hidden_segments(target, root)
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
    path: str = Query(..., min_length=1, description="Relative path from the scope root"),
    scope: Literal["tenant", "platform"] = Query("tenant"),
    current_user: UserModel = Depends(deps.get_current_active_user),
):
    """Read a file's contents. Caps at 256 KiB; binaries return a
    placeholder.

    Platform scope only serves docs-style extensions
    (.md/.txt/.rst/.yaml/.yml/.json); tenant scope serves anything the
    tenant owns.
    """
    root = _resolve_root(scope, current_user)
    target = _safe_join(root, path)
    # Reject hidden segments anywhere in the path (B1).
    _reject_hidden_segments(target, root)
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="path is a directory, not a file")
    if _is_hidden(target.name):
        raise HTTPException(status_code=404, detail="not found")

    # Platform scope: enforce extension allow-list (B3). Tenant scope
    # keeps the open contract.
    if scope == "platform":
        ext = target.suffix.lower()
        if ext not in _PLATFORM_ALLOWED_EXTS:
            raise HTTPException(
                status_code=404,
                detail="not found",
            )

    size = target.stat().st_size
    truncated = size > _MAX_FILE_BYTES
    raw = target.read_bytes()[:_MAX_FILE_BYTES]
    mime, _ = mimetypes.guess_type(target.name)
    mime = mime or "text/plain"
    # Binary detection: attempt UTF-8 decode; UnicodeDecodeError marks
    # the file as binary. Docstring at the top of the module documents
    # this choice (kept aligned with implementation per I1).
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
