"""Adversarial tests proving _run does NOT expand shell metacharacters.

Each test mounts a payload containing a specific shell metacharacter
class into a user-derived argument (branch_name / commit_msg / tag).
The payload attempts to create a canary file. The test asserts the
canary file does NOT exist post-call → no shell expansion fired.

Spec:
  docs/superpowers/specs/2026-05-22-subproject-a-infra-secret-hardening-design.md
PR1 (F1 shell=True removal).

Plan:
  docs/superpowers/plans/2026-05-22-pr1-shell-true-removal.md
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Existing code-worker test convention: `import workflows as wf` then
# `wf._run(...)`. The conftest.py at apps/code-worker/tests/ adds the
# package root to sys.path so `workflows` resolves as a top-level
# module when pytest is invoked from `apps/code-worker/`.
import workflows as wf


@pytest.fixture
def canary_path(tmp_path: Path) -> Path:
    """Per-test canary file. Path uniquely identifies the injection class."""
    canary = tmp_path / "canary_should_not_exist.txt"
    if canary.exists():
        canary.unlink()
    yield canary
    if canary.exists():
        canary.unlink()


@pytest.fixture
def workspace_with_git(tmp_path: Path) -> Path:
    """Minimal git workspace so commands like `git status` succeed."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=ws, check=True)
    return ws


def test_dollar_paren_substitution_is_literal(
    canary_path: Path, workspace_with_git: Path
):
    """`$(command)` MUST NOT execute. Payload tries to touch a canary."""
    branch_name = f"feat/x$(touch {canary_path})y"
    # We use `git checkout -b <branch>` which is one of the F1 sinks.
    try:
        wf._run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(workspace_with_git),
        )
    except RuntimeError:
        # Git may reject the branch name itself — that's fine. What we care
        # about is that the canary did NOT get created.
        pass
    assert not canary_path.exists(), (
        f"$(...) was expanded by the shell; canary at {canary_path} appeared. "
        "shell=True regression."
    )
