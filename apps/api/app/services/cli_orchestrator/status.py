"""Normalised CLI execution status — see design §2.

A single ``StrEnum`` is the contract every adapter returns and every
consumer (router, RL, council, chat-error-footer) reads. We deliberately
keep this enum small and extensible: new failure classes get a new value
plus a new row in the §2 classification table plus a named test in
``tests/cli_orchestrator/test_classification.py``. Clients render values
they don't know about as ``UNKNOWN_FAILURE`` (documented contract).
"""
from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """Resilient CLI orchestrator failure-class enum.

    Stable wire values — the lowercase string is the contract, do not
    reorder or rename without a migration plan for downstream consumers
    (RL experiences, ChatMessage.metadata, dashboards).
    """

    EXECUTION_SUCCEEDED = "execution_succeeded"
    """The adapter ran the CLI to completion with exit code 0."""

    NEEDS_AUTH = "needs_auth"
    """Missing / expired / revoked credentials. Phase 2 contract: stop
    + actionable_hint, never silent fallback."""

    QUOTA_EXHAUSTED = "quota_exhausted"
    """Rate limit, credit balance, monthly cap. Phase 2 contract: drop
    platform from chain, mark cooldown, fall back to next platform."""

    WORKSPACE_UNTRUSTED = "workspace_untrusted"
    """Codex trust_level / Gemini workspace setup. Phase 2 contract:
    stop + actionable_hint."""

    API_DISABLED = "api_disabled"
    """GCP API not enabled, GitHub Copilot not enabled for org. Phase 2
    contract: stop + actionable_hint."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """CLI binary missing, MCP server down, recursion gate exhausted.
    Phase 2 contract: fall back to next platform (no cooldown)."""

    RETRYABLE_NETWORK_FAILURE = "retryable_network_failure"
    """ECONNRESET, 503, transient TLS handshake. Phase 2 contract:
    retry once with backoff, then fall back."""

    TIMEOUT = "timeout"
    """Activity heartbeat timeout / subprocess kill. Phase 2 contract:
    retry once with extended timeout, then fall back."""

    WORKFLOW_FAILED = "workflow_failed"
    """Temporal CancelledError / ApplicationFailure / ActivityError —
    a Temporal-level failure already torn the activity down. Phase 2
    contract: stop, preserve workflow_id + activity_id."""

    UNKNOWN_FAILURE = "unknown_failure"
    """Classifier hit nothing — quarantine for §4.1 SLO tracking. Phase 2
    contract: retry once, then stop with the redacted snippet."""
