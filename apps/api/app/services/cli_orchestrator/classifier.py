# DEPRECATED — Phase 2 migrate callers to cli_orchestrator.classifier
# Phase 1.5 shim — re-export the canonical module from
# <repo-root>/packages/cli_orchestrator/classifier.py. The explicit
# private-symbol re-exports below keep module-attribute lookups working
# for tests and callers that historically reached for them.
from cli_orchestrator.classifier import *  # noqa: F401,F403
from cli_orchestrator.classifier import (  # noqa: F401
    _EXCEPTION_RULES,
    _Rule,
    _STDERR_RULES,
    classify,
    classify_with_legacy_label,
)
