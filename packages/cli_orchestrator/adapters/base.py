"""Provider adapter Protocol + request/result dataclasses — design §1 + §4.

Every concrete adapter (the 6 worker-side per-CLI executors plus the
api-side ``TemporalActivityAdapter``) implements this Protocol. The
``ResilientExecutor`` consumes the Protocol — it does not see any
worker-only or temporal-only types directly. That's how we keep the
api/worker import boundary clean: the Protocol lives in the canonical
shared package, concrete adapters live next to the things they wrap.

Wire-shape contract (test gate:
``apps/api/tests/cli_orchestrator/test_provider_adapter_contract.py``):

  - ``ProviderAdapter.name`` is a str literal — one of
    ``claude_code``, ``codex``, ``gemini_cli``, ``copilot_cli``,
    ``opencode``, ``shell``, ``temporal_activity``.
  - ``preflight(req) -> PreflightResult`` is sync (Phase 2). Adapters
    that need network I/O (Redis API-disabled cache) move to async in
    Phase 3 once we have the surrounding event-loop machinery.
  - ``run(req) -> ExecutionResult`` is sync. The api-side
    ``TemporalActivityAdapter`` internally drives an event loop via
    ``asyncio.run`` (or schedules a thread-pool when called from
    inside one), but the adapter surface stays sync so the executor
    is sync end-to-end. This mirrors the existing
    ``cli_session_manager.run_agent_session`` pattern.
  - ``classify_error(stderr, exit_code, exc) -> Status`` delegates to
    the canonical classifier — same signature for every adapter so the
    contract test is mechanical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from ..status import Status


# --------------------------------------------------------------------------
# ExecutionRequest — input to the adapter
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionRequest:
    """One unit-of-work the executor hands to an adapter.

    Args:
        chain: Ordered list of platform names the executor will walk on
            failure. The adapter sees the full chain so adapters that
            want to surface "we tried X then Y" (today's
            ``routing_summary``) can.
        platform: The specific platform the executor wants this adapter
            to handle. Always equals ``chain[attempt-1]`` for normal
            chain walks; the executor passes both for clarity.
        payload: Free-form dict carrying the adapter-specific call
            arguments. For chat: ``{"message": ..., "agent_slug": ...,
            "tenant_id": ..., ...}``. The keys are documented per
            adapter, not on the dataclass — the dataclass is the
            transport, the keys are the adapter's contract.
        parent_chain: Lineage of dispatching agents (UUIDs, possibly
            empty). The §3.1 recursion gate refuses any request where
            ``len(parent_chain) >= MAX_FALLBACK_DEPTH`` or the
            dispatching agent's UUID is already in the chain.
        tenant_id: Required for tenant-scoped credential fetch and
            cooldown bookkeeping. The adapter MUST treat it as
            authoritative — never read tenant from session-level state.
        run_id: Optional — populated by the executor for log
            correlation. Adapters echo it on the result.
    """

    chain: tuple[str, ...]
    platform: str
    payload: dict[str, Any]
    parent_chain: tuple = field(default_factory=tuple)
    tenant_id: Optional[str] = None
    run_id: Optional[str] = None


# --------------------------------------------------------------------------
# PreflightResult — output of preflight()
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PreflightResult:
    """Outcome of an adapter's pre-spawn safety checks.

    A successful preflight returns ``ok=True, status=None``. A failure
    returns ``ok=False`` plus the matching ``Status`` (PROVIDER_UNAVAILABLE,
    NEEDS_AUTH, WORKSPACE_UNTRUSTED, or API_DISABLED) so the executor /
    fallback policy treat it identically to a runtime failure.

    Preflight failures do NOT count toward ``attempt_count`` — they're
    stable, not transient — but they DO appear in ``platform_attempted``
    so the metadata accurately reflects what was tried.
    """

    ok: bool
    status: Optional[Status] = None
    reason: str = ""

    @classmethod
    def succeed(cls) -> "PreflightResult":
        return cls(ok=True)

    @classmethod
    def fail(cls, status: Status, reason: str) -> "PreflightResult":
        return cls(ok=False, status=status, reason=reason)


# --------------------------------------------------------------------------
# ExecutionResult — output of run()
# --------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """The terminal outcome the executor returns to its caller.

    The executor never raises — it always returns ExecutionResult.

    Attributes:
        status: Normalised ``Status`` enum.
        platform: The platform that produced this terminal result. May
            differ from ``ExecutionRequest.platform`` when fallback
            fired — it's the LAST platform the executor walked to.
        response_text: Empty string on failure paths, the assistant
            response on success. Already redacted at the boundary.
        stdout_summary: Up-to-4KB redacted snippet of subprocess stdout
            (or workflow result body for TemporalActivityAdapter). Used
            by the chat error footer + RL state text.
        stderr_summary: Same shape as stdout_summary, for stderr.
        exit_code: Subprocess exit code or workflow non-zero indicator.
            ``None`` when only an exception was raised.
        error_message: Redacted human-readable error string.
        platform_attempted: Ordered list of platforms the executor
            walked. Includes both successful and failed steps.
        attempt_count: Total attempts across all platforms.
        actionable_hint: i18n key surfaced to the UI when the chain
            stops on a recoverable-by-user error. Set on §3.2
            fallthrough as a NON-BLOCKING annotation when the chain
            ends in success on a downstream platform like opencode.
        workflow_id, activity_id: Populated when the adapter ran inside
            a Temporal workflow / activity. Preserved across
            WORKFLOW_FAILED so callers can drill into Temporal UI.
        metadata: Free-form passthrough — adapter-specific telemetry,
            tokens_in / tokens_out / cost_usd / etc. Merged into the
            chat ``ChatMessage.metadata`` JSON column at the boundary.
        run_id: Echoed back from the request for log correlation.
    """

    status: Status
    platform: str
    response_text: str = ""
    stdout_summary: str = ""
    stderr_summary: str = ""
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    platform_attempted: list[str] = field(default_factory=list)
    attempt_count: int = 0
    actionable_hint: Optional[str] = None
    workflow_id: Optional[str] = None
    activity_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status is Status.EXECUTION_SUCCEEDED

    def to_metadata_dict(self) -> dict[str, Any]:
        """Shape used by the chat hot path for ChatMessage.metadata.

        Stable keys — the chat UI footer (``routing_summary``) and the
        RL writer both read from here. New keys are additive; renames
        require coordinating with both consumers.
        """
        return {
            "status": self.status.value,
            "platform": self.platform,
            "platform_attempted": list(self.platform_attempted),
            "attempt_count": self.attempt_count,
            "actionable_hint": self.actionable_hint,
            "workflow_id": self.workflow_id,
            "activity_id": self.activity_id,
            "exit_code": self.exit_code,
            "error": self.error_message,
            "stdout_summary": self.stdout_summary,
            "stderr_summary": self.stderr_summary,
            **self.metadata,
        }


# --------------------------------------------------------------------------
# ProviderAdapter Protocol — design §1
# --------------------------------------------------------------------------

@runtime_checkable
class ProviderAdapter(Protocol):
    """The single seam between the executor and concrete adapters.

    ``runtime_checkable`` so the contract test can do
    ``isinstance(adapter, ProviderAdapter)`` rather than walking
    attributes by hand. Every concrete adapter ships its own contract
    test + fixture-driven preflight + run integration test.
    """

    name: str
    """One of: claude_code | codex | gemini_cli | copilot_cli |
    opencode | shell | temporal_activity."""

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        """Pre-spawn safety checks. Phase 2 budget: < 60ms uncached.

        Implementations:
          - shutil.which(<binary>) → PROVIDER_UNAVAILABLE on miss
          - credentials present in vault → NEEDS_AUTH on miss
          - workspace trust file → WORKSPACE_UNTRUSTED
          - cloud API enabled (cached 5min in Redis) → API_DISABLED

        Phase 2 ships only the binary-on-PATH check; deeper preflight
        lands in Phase 3.
        """
        ...

    def run(self, req: ExecutionRequest) -> ExecutionResult:
        """Execute the request. MUST NOT raise — return ExecutionResult.

        On success: status=EXECUTION_SUCCEEDED, response_text populated.

        On any failure: status=<classified>, error_message populated,
        stdout/stderr_summary redacted via ``cli_orchestrator.redact``.
        """
        ...

    def classify_error(
        self,
        stderr: Optional[str],
        exit_code: Optional[int],
        exc: Optional[BaseException],
    ) -> Status:
        """Delegate to the canonical classifier.

        Concrete adapters override only when they need platform-narrowed
        rules (today: none — the canonical classifier handles all
        platforms via its declaration-order rule list).
        """
        ...


__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "PreflightResult",
    "ProviderAdapter",
]
