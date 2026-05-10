"""ProviderAdapter contract tests — design §1.

Every concrete adapter (6 worker-side per-CLI executors plus the
api-side ``TemporalActivityAdapter``) is structurally validated against
the ``ProviderAdapter`` Protocol:

  - has a ``name: str`` attribute
  - implements ``preflight(req) -> PreflightResult``
  - implements ``run(req) -> ExecutionResult``
  - implements ``classify_error(stderr, exit_code, exc) -> Status``

The Protocol is ``runtime_checkable`` so we can do ``isinstance(adapter,
ProviderAdapter)``. We don't actually invoke any subprocess or Temporal
calls here — that's the integration-tier test. This is the structural
gate.

Layered: each step in the Phase 2 commit chain extends ``ADAPTER_FACTORIES``
with the next adapter; this single file is the final gate.
"""
from __future__ import annotations

import inspect
from typing import Callable

import pytest

from cli_orchestrator.adapters import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
    ProviderAdapter,
)
from cli_orchestrator.status import Status


# --------------------------------------------------------------------------
# Stub adapter used only to validate the Protocol surface itself
# --------------------------------------------------------------------------

class _StubAdapter:
    """Bare-minimum implementation — proves the Protocol's structural
    check actually fires when a class lacks the right methods.

    Used only by the test-the-test self-check below. The real adapters
    are picked up by their respective import-and-register sections."""

    name = "stub"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        return PreflightResult.succeed()

    def run(self, req: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(status=Status.EXECUTION_SUCCEEDED, platform=self.name)

    def classify_error(self, stderr, exit_code, exc) -> Status:
        return Status.UNKNOWN_FAILURE


# --------------------------------------------------------------------------
# Adapter factory registry — every concrete adapter registers a ()-call
# returning an instance suitable for structural tests (no subprocess).
# Each Phase 2 commit appends to this list.
# --------------------------------------------------------------------------

ADAPTER_FACTORIES: list[tuple[str, Callable[[], ProviderAdapter]]] = [
    ("stub", _StubAdapter),
]


# Phase 2 step 3 will register the api-side ``TemporalActivityAdapter``.
# Phase 2 step 4 will register the 6 worker-side concrete adapters
# (claude_code, codex, gemini_cli, copilot_cli, opencode, shell). Each
# step extends ``ADAPTER_FACTORIES`` and the test parametrisation picks
# the new rows up automatically.


# Try to import the api-side TemporalActivityAdapter — it lands in
# step 3, so this is a lazy attempt that adds the row when present.
def _try_register_temporal_activity() -> None:
    try:
        from cli_orchestrator.adapters.temporal_activity import TemporalActivityAdapter
    except ImportError:
        return
    ADAPTER_FACTORIES.append(
        ("temporal_activity", lambda: TemporalActivityAdapter(platform="claude_code"))
    )


_try_register_temporal_activity()


# Try to import the worker adapters — they land in step 4. The worker
# package is on sys.path when the worker conftest runs the test, not
# the api conftest, so api-side runs simply skip these rows.
def _try_register_worker_adapters() -> None:
    try:
        import cli_orchestrator_adapters  # noqa: F401
    except ImportError:
        return

    from cli_orchestrator_adapters.claude_code import ClaudeCodeAdapter
    from cli_orchestrator_adapters.codex import CodexAdapter
    from cli_orchestrator_adapters.gemini_cli import GeminiCliAdapter
    from cli_orchestrator_adapters.copilot_cli import CopilotCliAdapter
    from cli_orchestrator_adapters.opencode import OpencodeAdapter
    from cli_orchestrator_adapters.shell import ShellAdapter

    ADAPTER_FACTORIES.extend([
        ("claude_code", ClaudeCodeAdapter),
        ("codex", CodexAdapter),
        ("gemini_cli", GeminiCliAdapter),
        ("copilot_cli", CopilotCliAdapter),
        ("opencode", OpencodeAdapter),
        ("shell", ShellAdapter),
    ])


_try_register_worker_adapters()


# --------------------------------------------------------------------------
# Structural gate
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,factory", ADAPTER_FACTORIES, ids=lambda x: x if isinstance(x, str) else x.__name__,
)
def test_adapter_implements_protocol(name, factory):
    """Every concrete adapter satisfies ``ProviderAdapter`` structurally."""
    adapter = factory()
    # ``runtime_checkable`` Protocol — checks attribute existence, not
    # signatures. We follow up with a separate signature gate below.
    assert isinstance(adapter, ProviderAdapter), (
        f"{name}: missing one of preflight/run/classify_error/name attribute"
    )
    assert isinstance(adapter.name, str) and adapter.name, (
        f"{name}: ``name`` must be a non-empty string"
    )


@pytest.mark.parametrize(
    "name,factory", ADAPTER_FACTORIES, ids=lambda x: x if isinstance(x, str) else x.__name__,
)
def test_adapter_signatures(name, factory):
    """Every adapter's preflight/run/classify_error has the documented signature."""
    adapter = factory()

    pf_sig = inspect.signature(adapter.preflight)
    pf_params = list(pf_sig.parameters.keys())
    assert pf_params == ["req"], f"{name}.preflight: expected (req), got {pf_params}"

    run_sig = inspect.signature(adapter.run)
    run_params = list(run_sig.parameters.keys())
    assert run_params == ["req"], f"{name}.run: expected (req), got {run_params}"

    cls_sig = inspect.signature(adapter.classify_error)
    cls_params = list(cls_sig.parameters.keys())
    assert cls_params == ["stderr", "exit_code", "exc"], (
        f"{name}.classify_error: expected (stderr, exit_code, exc), got {cls_params}"
    )


# --------------------------------------------------------------------------
# Self-check — the Protocol catches a non-conformant class
# --------------------------------------------------------------------------

def test_protocol_catches_non_conformant_class():
    """If someone forgets a method, isinstance() returns False."""

    class _Broken:
        name = "broken"

        # missing preflight, run, classify_error

    assert not isinstance(_Broken(), ProviderAdapter)
