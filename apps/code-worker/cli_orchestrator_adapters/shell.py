"""ShellAdapter — wraps cli_runtime.run_cli_with_heartbeat for skill execution.

Phase 2 worker-side ProviderAdapter for arbitrary shell commands — the
sibling of the per-CLI adapters that's used for skill execution and
generic shell fan-out (the spot where the orchestrator runs a non-CLI
binary that still needs heartbeat-aware subprocess management).

Unlike the per-CLI adapters this one does NOT call into a
``cli_executors`` executor. It calls ``cli_runtime.run_cli_with_heartbeat``
directly. The payload supplies ``cmd: list[str]``, ``label: str``, and
optional ``timeout``, ``env``, ``cwd``, ``heartbeat_interval``.

Preflight checks the first element of ``cmd`` is on ``$PATH``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.classifier import classify
from cli_orchestrator.redaction import redact
from cli_orchestrator.status import Status

import cli_runtime

from ._common import binary_on_path, truncate

logger = logging.getLogger(__name__)


class ShellAdapter:
    name = "shell"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        cmd = (req.payload or {}).get("cmd") or []
        if not cmd:
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                "shell adapter requires payload['cmd'] list",
            )
        binary = cmd[0]
        if not binary_on_path(binary):
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                f"`{binary}` binary not on $PATH",
            )
        return PreflightResult.succeed()

    def classify_error(
        self,
        stderr: Optional[str],
        exit_code: Optional[int],
        exc: Optional[BaseException],
    ) -> Status:
        return classify(stderr, exit_code, exc)

    def run(self, req: ExecutionRequest) -> ExecutionResult:
        run_id = req.run_id or str(uuid.uuid4())
        payload = req.payload or {}
        cmd = list(payload.get("cmd") or [])
        if not cmd:
            err = "shell adapter requires payload['cmd'] list"
            return ExecutionResult(
                status=Status.PROVIDER_UNAVAILABLE,
                platform=self.name,
                response_text="",
                error_message=err,
                stderr_summary=err,
                platform_attempted=[self.name],
                attempt_count=1,
                run_id=run_id,
            )
        label = payload.get("label") or "shell"
        timeout = int(payload.get("timeout") or 1500)
        env = payload.get("env")
        cwd = payload.get("cwd")
        heartbeat_interval = int(payload.get("heartbeat_interval") or 30)
        try:
            result = cli_runtime.run_cli_with_heartbeat(
                cmd,
                label=label,
                timeout=timeout,
                env=env,
                cwd=cwd,
                heartbeat_interval=heartbeat_interval,
            )
        except BaseException as exc:  # noqa: BLE001
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "ShellAdapter.run raised — classified as %s: %s",
                status.value, err,
            )
            return ExecutionResult(
                status=status,
                platform=self.name,
                response_text="",
                error_message=err,
                stderr_summary=truncate(err),
                platform_attempted=[self.name],
                attempt_count=1,
                run_id=run_id,
            )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code = result.returncode
        if exit_code == 0:
            redacted = redact(stdout)
            return ExecutionResult(
                status=Status.EXECUTION_SUCCEEDED,
                platform=self.name,
                response_text=redacted,
                stdout_summary=truncate(redacted),
                stderr_summary=truncate(redact(stderr)),
                exit_code=exit_code,
                platform_attempted=[self.name],
                attempt_count=1,
                run_id=run_id,
            )
        # Non-zero exit — classify the stderr / extracted error.
        snippet = cli_runtime.safe_cli_error_snippet(stderr, stdout, 800)
        status = self.classify_error(stderr=snippet, exit_code=exit_code, exc=None)
        err_redacted = redact(snippet)
        return ExecutionResult(
            status=status,
            platform=self.name,
            response_text="",
            error_message=err_redacted,
            stdout_summary=truncate(redact(stdout)),
            stderr_summary=truncate(err_redacted),
            exit_code=exit_code,
            platform_attempted=[self.name],
            attempt_count=1,
            run_id=run_id,
        )


__all__ = ["ShellAdapter"]
