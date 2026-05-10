# DEPRECATED — Phase 2 migrate callers to cli_orchestrator.*
# Phase 1.5 shim — the canonical home is <repo-root>/packages/cli_orchestrator/.
# This module re-exports the public surface so existing apps/api callers and
# the 85 cli_orchestrator unit tests keep their ``app.services.cli_orchestrator``
# import paths working without modification.
from cli_orchestrator import *  # noqa: F401,F403
from cli_orchestrator import __all__  # noqa: F401
