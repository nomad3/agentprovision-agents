"""Shared helpers for worker-side ProviderAdapter implementations.

Two helpers:

  - ``binary_on_path(name)`` — memoised ``shutil.which`` for adapter
    preflight. Cached at module load so steady-state preflight cost is
    a dict lookup, not a fork+exec. The memo is keyed by binary name;
    it never expires within a worker process. The worker pod cycles
    on deploy so a stale "not present" memo is washed out by the
    deploy; if you need fresh detection across deploys, restart the
    pod (already SOP).

  - ``map_chat_cli_result_to_execution_result(...)`` — turns a
    ``ChatCliResult`` (response_text/success/error/metadata) plus the
    requesting platform into an ``ExecutionResult`` with the right
    Status, redacted snippets, and platform_attempted populated.
"""
from __future__ import annotations

import shutil
from typing import Optional

from cli_orchestrator.adapters.base import ExecutionResult
from cli_orchestrator.classifier import classify
from cli_orchestrator.redaction import redact
from cli_orchestrator.status import Status

# 4KB cap on stdout/stderr summaries — design §4 (redacted, max 4KB).
SUMMARY_MAX_BYTES = 4096


_WHICH_CACHE: dict[str, Optional[str]] = {}


def binary_on_path(name: str) -> bool:
    """Memoised ``shutil.which`` — preflight binary check.

    Cached at the process level. Returns True iff the binary exists on
    ``$PATH`` at the time of first lookup. Worker pods cycle on deploy
    so any stale cache is washed out.
    """
    if name not in _WHICH_CACHE:
        _WHICH_CACHE[name] = shutil.which(name)
    return _WHICH_CACHE[name] is not None


def truncate(text: str) -> str:
    if not text:
        return ""
    if len(text) <= SUMMARY_MAX_BYTES:
        return text
    return text[:SUMMARY_MAX_BYTES] + "\n…(truncated)"


def map_chat_cli_result_to_execution_result(
    *,
    cli_result,
    platform: str,
    run_id: Optional[str] = None,
) -> ExecutionResult:
    """Convert a worker-side ChatCliResult to an ExecutionResult.

    Args:
        cli_result: Object with ``response_text: str``, ``success: bool``,
            ``error: Optional[str]``, ``metadata: Optional[dict]``. The
            duck-type matches both the dataclass form (``ChatCliResult``
            from workflows.py) and the dict form some tests use.
        platform: The CLI platform name being adapted.
        run_id: Optional log-correlation id.

    Returns:
        ``ExecutionResult`` with status / response_text / error_message
        / stdout/stderr_summary populated, redacted at the boundary.
    """
    if isinstance(cli_result, dict):
        success = bool(cli_result.get("success", False))
        response_text = cli_result.get("response_text", "") or ""
        error = cli_result.get("error")
        meta = cli_result.get("metadata") or {}
    else:
        success = bool(getattr(cli_result, "success", False))
        response_text = getattr(cli_result, "response_text", "") or ""
        error = getattr(cli_result, "error", None)
        meta = getattr(cli_result, "metadata", None) or {}

    if success and response_text:
        redacted = redact(response_text)
        return ExecutionResult(
            status=Status.EXECUTION_SUCCEEDED,
            platform=platform,
            response_text=redacted,
            stdout_summary=truncate(redacted),
            exit_code=0,
            platform_attempted=[platform],
            attempt_count=1,
            metadata=dict(meta) if isinstance(meta, dict) else {},
            run_id=run_id,
        )

    err_text = error or "CLI returned empty response"
    status = classify(stderr=err_text, exit_code=None, exc=None)
    err_redacted = redact(err_text)
    return ExecutionResult(
        status=status,
        platform=platform,
        response_text="",
        error_message=err_redacted,
        stderr_summary=truncate(err_redacted),
        platform_attempted=[platform],
        attempt_count=1,
        metadata=dict(meta) if isinstance(meta, dict) else {},
        run_id=run_id,
    )


# --------------------------------------------------------------------------
# Phase 3 commit 2 — per-adapter preflight composition
# --------------------------------------------------------------------------

def time_preflight_helper(platform: str, helper_name: str):
    """Context-manager that emits ``cli_orchestrator_preflight_duration_ms``.

    Used by adapters to instrument each helper call. Best-effort —
    failures to emit metrics are swallowed.

    Usage:
        with time_preflight_helper("codex", "binary_on_path"):
            result = check_binary_on_path("codex")
    """
    from contextlib import contextmanager
    import time as _time

    @contextmanager
    def _ctx():
        try:
            from cli_orchestrator.executor import (
                _METRICS_OK,
                _PREFLIGHT_DURATION_MS,
            )
        except Exception:  # noqa: BLE001
            _METRICS_OK = False
            _PREFLIGHT_DURATION_MS = None  # type: ignore[assignment]
        t0 = _time.perf_counter()
        try:
            yield
        finally:
            if _METRICS_OK and _PREFLIGHT_DURATION_MS is not None:
                try:
                    _PREFLIGHT_DURATION_MS.labels(
                        platform=platform, helper=helper_name,
                    ).observe((_time.perf_counter() - t0) * 1000.0)
                except Exception:  # noqa: BLE001
                    pass

    return _ctx()


# Codex / Gemini workspace trust file paths — design §6 row 3.
# Codex writes ~/.codex/config.toml on `codex auth`. Gemini's setup
# marker is the existence of GOOGLE_APPLICATION_CREDENTIALS or the
# default ~/.config/gemini/oauth.json (handled separately, today only
# codex composes a workspace check).
_WORKSPACE_TRUST_FILES = {
    "codex": "~/.codex/config.toml",
}


def check_credential_for_platform(
    deps,
    tenant_id: str,
    platform: str,
):
    """Compose ``check_credentials_present`` against the worker's
    PreflightDeps.

    Phase 3 commit 2 helper — used by the 4 adapters that need a
    NEEDS_AUTH preflight check (claude_code, codex, gemini_cli,
    copilot_cli). Returns a ``PreflightResult``; opencode + shell
    don't need this (no per-tenant credentials).
    """
    from cli_orchestrator.preflight import check_credentials_present

    return check_credentials_present(
        fetch=deps.credential_fetch,
        tenant_id=tenant_id,
        platform=platform,
    )


def check_workspace_trust_file_for_platform(platform: str):
    """Compose ``check_workspace_trust_file`` for adapters that need
    it. Returns ``PreflightResult.succeed()`` when the platform has no
    workspace trust file (defensive — the executor still walks the
    rest of preflight)."""
    from cli_orchestrator.adapters.base import PreflightResult
    from cli_orchestrator.preflight import check_workspace_trust_file

    path = _WORKSPACE_TRUST_FILES.get(platform)
    if path is None:
        return PreflightResult.succeed()
    return check_workspace_trust_file(path)


__all__ = [
    "SUMMARY_MAX_BYTES",
    "binary_on_path",
    "truncate",
    "map_chat_cli_result_to_execution_result",
    "check_credential_for_platform",
    "check_workspace_trust_file_for_platform",
    "time_preflight_helper",
]
