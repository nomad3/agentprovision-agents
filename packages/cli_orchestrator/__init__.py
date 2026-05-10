"""CLI orchestrator package — Phase 1 + Phase 2 surface.

Phase 1 ships:
  - ``Status`` normalised failure-class enum
  - ``classify(stderr, exit_code, exc) -> Status`` — single classifier
  - ``classify_with_legacy_label(...)`` — legacy ``"quota"`` / ``"auth"`` /
    ``"missing_credential"`` / ``None`` mapping kept for the existing
    ``cli_platform_resolver.classify_error`` wrapper contract
  - ``redact(text)`` and ``redact_json_structural(payload)`` — secret scrub
  - ``cleanup_codex_home(path)`` — idempotent ``~/.codex`` rmtree helper
  - ``SENSITIVE_ENV_KEYS`` — extends ``skill_manager._SENSITIVE_ENV_KEYS``
    with platform-token names.

Phase 2 ships:
  - ``FallbackDecision`` + ``decide(...)`` + ``MAX_FALLBACK_DEPTH`` — pure
    fallback policy (design §3 + §3.1 + §3.2 R1).
  - ``ProviderAdapter`` Protocol + ``ExecutionRequest`` / ``ExecutionResult``
    / ``PreflightResult`` dataclasses (``adapters.base``).
  - ``TemporalActivityAdapter`` (``adapters.temporal_activity``) — api-side
    adapter that dispatches ``ChatCliWorkflow``.
  - ``ResilientExecutor`` (``executor``) — sync chain walker that applies
    preflight + retry + fallback + redaction + Prometheus metrics.
  - ``shadow`` — agreement-metric plumbing for the flag-off cutover gate.
"""
from .adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
    ProviderAdapter,
)
from .classifier import classify, classify_with_legacy_label
from .executor import ResilientExecutor
from .policy import (
    FallbackAction,
    FallbackDecision,
    MAX_FALLBACK_DEPTH,
    decide,
)
from .preflight import (
    check_binary_on_path,
    check_cloud_api_enabled,
    check_credentials_present,
    check_temporal_queue_reachable,
    check_workspace_trust_file,
)
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
    "FallbackAction",
    "FallbackDecision",
    "MAX_FALLBACK_DEPTH",
    "decide",
    "ProviderAdapter",
    "ExecutionRequest",
    "ExecutionResult",
    "PreflightResult",
    "ResilientExecutor",
    "check_binary_on_path",
    "check_workspace_trust_file",
    "check_credentials_present",
    "check_cloud_api_enabled",
    "check_temporal_queue_reachable",
]
