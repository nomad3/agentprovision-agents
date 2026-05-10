"""Top-level conftest for the apps/api test suite.

Phase 1.5 (cli-orchestrator I-1 mitigation): the canonical home for
``cli_orchestrator.*`` is ``<repo-root>/packages/cli_orchestrator/``.
At runtime the API container COPYs that directory into ``/app/`` so the
``cli_orchestrator`` import resolves out-of-the-box. For local pytest
runs we add the repo-root ``packages/`` directory to ``sys.path`` here,
mirroring the worker conftest in ``apps/code-worker/tests/conftest.py``.

Both runtimes use the same approach (absolute path, computed from
``Path(__file__)``) — no relative pytest-ini paths, no editable install,
no PYTHONPATH env-var dependency.
"""
from __future__ import annotations

import sys
from pathlib import Path

# apps/api/conftest.py → apps/api → apps → <repo-root>
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES_DIR = REPO_ROOT / "packages"
if PACKAGES_DIR.is_dir() and str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))

# Eagerly import the canonical ``cli_orchestrator`` package so it lands in
# ``sys.modules`` BEFORE pytest walks ``apps/api/tests/`` and discovers the
# similarly-named test subpackage ``apps/api/tests/cli_orchestrator/`` (an
# unrelated test directory that happens to share the name). Without this
# line, the test dir's empty ``__init__.py`` shadows the canonical package
# the moment any test module triggers ``from app.services.cli_orchestrator
# import ...`` — the apps/api shim re-exports from ``cli_orchestrator``,
# which would then resolve to the test subpackage instead.
import cli_orchestrator  # noqa: E402,F401  cache the canonical package
