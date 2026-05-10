# DEPRECATED — Phase 2 migrate callers to cli_orchestrator.redaction
# Phase 1.5 shim — re-export the canonical module from
# <repo-root>/packages/cli_orchestrator/redaction.py. The explicit
# private-symbol re-exports below keep module-attribute lookups working
# for tests and callers that historically reached for them.
from cli_orchestrator.redaction import *  # noqa: F401,F403
from cli_orchestrator.redaction import (  # noqa: F401
    _RULES,
    _STRUCTURAL_KEY_RE,
    SENSITIVE_ENV_KEYS,
    cleanup_codex_home,
    redact,
    redact_json_structural,
)
