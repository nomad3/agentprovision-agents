"""CodexAdapter — wraps cli_executors.codex.execute_codex_chat.

Phase 2 worker-side ProviderAdapter for the ``codex`` platform. Mirrors
ClaudeCodeAdapter; the executor signature includes an ``image_path``
positional that's threaded through from the request payload.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from cli_orchestrator.adapters.base import (
    ExecutionRequest,
    ExecutionResult,
    PreflightResult,
)
from cli_orchestrator.classifier import classify
from cli_orchestrator.redaction import redact
from cli_orchestrator.status import Status

from cli_executors.codex import execute_codex_chat

from ._common import (
    binary_on_path,
    map_chat_cli_result_to_execution_result,
    truncate,
)

logger = logging.getLogger(__name__)


@dataclass
class _MinimalChatCliInput:
    platform: str
    message: str
    tenant_id: str
    instruction_md_content: str = ""
    mcp_config: str = ""
    image_b64: str = ""
    image_mime: str = ""
    session_id: str = ""
    model: str = ""
    allowed_tools: str = ""


class CodexAdapter:
    name = "codex"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        if not binary_on_path("codex"):
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                "`codex` binary not on $PATH",
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
        session_dir = payload.get("session_dir") or "/tmp"
        image_path = payload.get("image_path") or ""
        task_input = _MinimalChatCliInput(
            platform=self.name,
            message=payload.get("message", ""),
            tenant_id=req.tenant_id or payload.get("tenant_id", ""),
            instruction_md_content=payload.get("instruction_md_content", ""),
            mcp_config=payload.get("mcp_config", ""),
            image_b64=payload.get("image_b64", ""),
            image_mime=payload.get("image_mime", ""),
            session_id=payload.get("session_id", ""),
            model=payload.get("model", ""),
            allowed_tools=payload.get("allowed_tools", ""),
        )
        try:
            cli_result = execute_codex_chat(task_input, session_dir, image_path)
        except BaseException as exc:  # noqa: BLE001
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "CodexAdapter.run raised — classified as %s: %s",
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
        return map_chat_cli_result_to_execution_result(
            cli_result=cli_result, platform=self.name, run_id=run_id,
        )


__all__ = ["CodexAdapter"]
