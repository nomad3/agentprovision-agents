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


__all__ = [
    "SUMMARY_MAX_BYTES",
    "binary_on_path",
    "truncate",
    "map_chat_cli_result_to_execution_result",
]
