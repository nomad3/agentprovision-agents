"""Tests for `POST /api/v1/workspace/clone` (task #255).

Locks the security + contract guarantees the CLI `alpha workspace
clone` and the FE empty-state both depend on:

- Endpoint requires auth (401 without a current_user override)
- Tenant resolved from the JWT, not request body (no spoofing other
  tenants' workspaces)
- GitHub token is fetched from the user's integration row via the
  credential vault (mocked here — no real network)
- Subprocess invocation passes the right URL + target path + branch
- 200 + {job_id, status:"started"} returned synchronously while the
  clone runs in the BackgroundTasks pool
- Idempotency: when the target dir already exists with `.git/`, the
  background job does `git fetch` + `git reset --hard`, NOT `git clone`
- Repo input is validated: shell metas, path traversal (`..`), and
  malformed shapes all 400
- Missing github integration → 409 (so the CLI/UI can prompt the
  user to connect github), not 500
"""
from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── fixtures ─────────────────────────────────────────────────────────


def _fake_user(*, tenant_id: str | None, is_superuser: bool = False):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.UUID(tenant_id) if tenant_id else None
    u.is_active = True
    u.is_superuser = is_superuser
    u.email = "clone-test@example.test"
    return u


@pytest.fixture
def workspaces_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point WORKSPACES_ROOT at a tmp dir and reload the workspace
    module so the module-level constant picks up the env."""
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setenv("WORKSPACES_ROOT", str(root))
    from app.api.v1 import workspace as workspace_mod

    importlib.reload(workspace_mod)
    return root


def _client_for(user, *, github_token: str | None = "ghs_testtoken123") -> TestClient:
    """Build a single-router FastAPI app with the user injected via
    dependency override + a stub get_db that returns a no-op session.

    The github-token lookup is patched at the module level to avoid
    pulling in the credential vault for unit tests.
    """
    from app.api import deps
    from app.api.v1 import workspace as workspace_mod

    importlib.reload(workspace_mod)

    # Patch the token resolver — every test runs against this stub
    # unless it monkeypatches it explicitly.
    workspace_mod._resolve_github_token = MagicMock(return_value=github_token)

    app = FastAPI()
    app.include_router(workspace_mod.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    app.dependency_overrides[deps.get_db] = lambda: MagicMock()
    return TestClient(app)


# ── auth ─────────────────────────────────────────────────────────────


def test_clone_requires_auth(workspaces_root: Path):
    """Without the get_current_active_user override the endpoint must
    reject the request. We don't override it here on purpose."""
    from app.api import deps
    from app.api.v1 import workspace as workspace_mod

    importlib.reload(workspace_mod)

    app = FastAPI()
    app.include_router(workspace_mod.router, prefix="/api/v1")

    # Force the dependency to raise 401 — matches the real auth path
    # which raises HTTPException(401) on missing token.
    from fastapi import HTTPException

    def _unauthorized():
        raise HTTPException(status_code=401, detail="not authenticated")

    app.dependency_overrides[deps.get_current_active_user] = _unauthorized
    app.dependency_overrides[deps.get_db] = lambda: MagicMock()
    client = TestClient(app)

    r = client.post("/api/v1/workspace/clone", json={"repo": "owner/name"})
    assert r.status_code == 401, r.text


# ── happy path ───────────────────────────────────────────────────────


def test_clone_happy_path_calls_git_clone(workspaces_root: Path):
    tenant = "11111111-1111-1111-1111-111111111111"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user)

    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        r = client.post(
            "/api/v1/workspace/clone",
            json={"repo": "nomad3/agentprovision-agents"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "started"
    assert body["job_id"]  # non-empty
    assert body["owner"] == "nomad3"
    assert body["repo"] == "agentprovision-agents"
    # target is reported as workspace-relative (projects/<repo>)
    assert body["target_path"].endswith("projects/agentprovision-agents")

    # Subprocess must have been invoked with a `git clone` containing
    # the token-bearing URL and the resolved target path. The first
    # call is the clone (no existing dir).
    assert run.called
    args_seen = [c.args[0] if c.args else c.kwargs.get("args") for c in run.call_args_list]
    clone_calls = [a for a in args_seen if isinstance(a, list) and a[:2] == ["git", "clone"]]
    assert clone_calls, f"expected a `git clone` invocation, got: {args_seen}"
    clone_argv = clone_calls[0]
    # URL must embed the token and point at github.com
    url = clone_argv[-2]
    assert url.startswith("https://ghs_testtoken123@github.com/nomad3/agentprovision-agents.git"), url
    target_arg = clone_argv[-1]
    assert target_arg.endswith("projects/agentprovision-agents"), target_arg
    assert tenant in target_arg


def test_clone_with_branch_passes_branch_flag(workspaces_root: Path):
    tenant = "22222222-2222-2222-2222-222222222222"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user)

    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        r = client.post(
            "/api/v1/workspace/clone",
            json={"repo": "owner/name", "branch": "release/1.2"},
        )
    assert r.status_code == 200
    clone_argv = next(
        c.args[0] for c in run.call_args_list
        if c.args and isinstance(c.args[0], list) and c.args[0][:2] == ["git", "clone"]
    )
    assert "--branch" in clone_argv
    assert clone_argv[clone_argv.index("--branch") + 1] == "release/1.2"


# ── idempotency ──────────────────────────────────────────────────────


def test_clone_idempotent_runs_fetch_reset(workspaces_root: Path):
    """Re-clone on a target that already exists must do `fetch +
    reset`, not `clone`."""
    tenant = "33333333-3333-3333-3333-333333333333"
    user = _fake_user(tenant_id=tenant)

    # Pre-create the target dir with a .git/ so the code-path takes
    # the refresh branch instead of clone.
    target = workspaces_root / tenant / "projects" / "name"
    (target / ".git").mkdir(parents=True)

    client = _client_for(user)
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        r = client.post(
            "/api/v1/workspace/clone",
            json={"repo": "owner/name", "branch": "main"},
        )
    assert r.status_code == 200, r.text

    cmds_seen = [c.args[0] for c in run.call_args_list if c.args and isinstance(c.args[0], list)]
    # No `git clone` should have been issued.
    assert not any(c[:2] == ["git", "clone"] for c in cmds_seen), cmds_seen
    # `git fetch` and `git reset --hard origin/main` should both appear.
    assert any(c[:2] == ["git", "fetch"] for c in cmds_seen), cmds_seen
    assert any(
        c[:3] == ["git", "reset", "--hard"] and c[-1] == "origin/main"
        for c in cmds_seen
    ), cmds_seen


# ── repo validation ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "evil",
    [
        "../etc/passwd",
        "owner/..",
        "owner/../name",
        "owner/name;rm -rf /",
        "owner/name`whoami`",
        "owner/name$(whoami)",
        "owner/name|cat",
        "owner//name",
        "owner/ name",  # space
        "",
        "no-slash-here",
        "https://gitlab.com/owner/name",  # non-github URL
    ],
)
def test_clone_rejects_malformed_repo(workspaces_root: Path, evil: str):
    tenant = "44444444-4444-4444-4444-444444444444"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user)

    with patch("subprocess.run") as run:
        r = client.post("/api/v1/workspace/clone", json={"repo": evil})
    assert r.status_code == 400, f"input {evil!r} should 400, got {r.status_code}: {r.text}"
    # And no subprocess must have been invoked for a rejected input.
    assert not run.called, f"git ran for rejected input {evil!r}"


@pytest.mark.parametrize(
    "bad_branch",
    [
        "branch with space",
        "branch;rm -rf",
        "branch`x`",
        "branch$(x)",
        "a" * 300,
    ],
)
def test_clone_rejects_malformed_branch(workspaces_root: Path, bad_branch: str):
    tenant = "55555555-5555-5555-5555-555555555555"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user)

    with patch("subprocess.run"):
        r = client.post(
            "/api/v1/workspace/clone",
            json={"repo": "owner/name", "branch": bad_branch},
        )
    assert r.status_code == 400, r.text


# ── github integration missing ───────────────────────────────────────


def test_clone_returns_409_when_no_github_token(workspaces_root: Path):
    tenant = "66666666-6666-6666-6666-666666666666"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user, github_token=None)

    with patch("subprocess.run") as run:
        r = client.post("/api/v1/workspace/clone", json={"repo": "owner/name"})
    assert r.status_code == 409, r.text
    assert "github" in r.json().get("detail", "").lower()
    assert not run.called


# ── tenant resolution ────────────────────────────────────────────────


def test_clone_uses_caller_tenant_not_body(workspaces_root: Path):
    """Even if a future field tried to spoof tenant_id in the body,
    the endpoint must use current_user.tenant_id. We assert by
    inspecting the resolved target path."""
    tenant = "77777777-7777-7777-7777-777777777777"
    user = _fake_user(tenant_id=tenant)
    client = _client_for(user)

    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
        # Body has an extra (ignored) field — must not influence the
        # target. FastAPI's pydantic model already strips unknown
        # fields by default, but this nails it down explicitly.
        r = client.post(
            "/api/v1/workspace/clone",
            json={"repo": "owner/name", "tenant_id": "deadbeef-0000-0000-0000-000000000000"},
        )
    assert r.status_code == 200, r.text
    clone_argv = next(
        c.args[0] for c in run.call_args_list
        if c.args and isinstance(c.args[0], list) and c.args[0][:2] == ["git", "clone"]
    )
    target_arg = clone_argv[-1]
    assert tenant in target_arg, target_arg
    assert "deadbeef" not in target_arg


def test_clone_rejects_user_without_tenant(workspaces_root: Path):
    user = _fake_user(tenant_id=None)
    client = _client_for(user)
    r = client.post("/api/v1/workspace/clone", json={"repo": "owner/name"})
    assert r.status_code == 400, r.text
