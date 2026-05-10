"""Provider adapter surface — design §1.

Phase 2 ships:
  - ``ProviderAdapter`` Protocol — the single seam every concrete
    adapter (worker-side per-CLI executors + api-side
    ``TemporalActivityAdapter``) implements.
  - ``ExecutionRequest``, ``ExecutionResult``, ``PreflightResult`` —
    dataclasses on the wire between the executor and adapters.

Phase 3+ will add per-adapter preflight depth (Redis-backed API-disabled
cache, Codex trust-file checks, etc.). Phase 2 keeps preflight as a
binary-on-PATH check + memoised platform availability.
"""
from .base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
    ProviderAdapter,
)

__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "PreflightResult",
    "ProviderAdapter",
]
