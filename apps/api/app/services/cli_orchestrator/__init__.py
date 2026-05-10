"""CLI orchestrator package — Phase 1 (error contract + redaction primitives).

Phase 1 ships:
  - ``Status`` normalised failure-class enum
  - ``classify(stderr, exit_code, exc) -> Status`` — single classifier
  - ``classify_with_legacy_label(...)`` — legacy ``"quota"`` / ``"auth"`` /
    ``"missing_credential"`` / ``None`` mapping kept for the existing
    ``cli_platform_resolver.classify_error`` wrapper contract
  - ``redact(text)`` and ``redact_json_structural(payload)`` — secret scrub
  - ``cleanup_codex_home(path)`` — idempotent ``~/.codex`` rmtree helper
  - ``SENSITIVE_ENV_KEYS`` — extends ``skill_manager._SENSITIVE_ENV_KEYS``
    with platform-token names. Defined here, not wired anywhere yet —
    Phase 2 adapters import it.

No ``ProviderAdapter``, no ``FallbackPolicy``, no ``ResilientExecutor``,
no ``ExecutionMetadata`` are exported in Phase 1 — those land in Phase 2.
"""
from .classifier import classify, classify_with_legacy_label
from .redaction import (
    SENSITIVE_ENV_KEYS,
    cleanup_codex_home,
    redact,
    redact_json_structural,
)
from .status import Status

__all__ = [
    "Status",
    "classify",
    "classify_with_legacy_label",
    "redact",
    "redact_json_structural",
    "cleanup_codex_home",
    "SENSITIVE_ENV_KEYS",
]
