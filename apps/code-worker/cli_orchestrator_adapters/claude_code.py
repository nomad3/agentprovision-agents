"""ClaudeCodeAdapter — wraps cli_executors.claude.execute_claude_chat.

Phase 2 worker-side ProviderAdapter for the ``claude_code`` platform.
The ``run()`` method calls the public executor function hoisted in
Phase 1.6 — ``cli_executors.claude.execute_claude_chat`` — which is
importable WITHOUT dragging ``workflows.py`` into the import graph
(the executor body's own ``from workflows import ...`` runs lazily on
first call).

Phase 2 scope is "scaffold + contract-test + per-platform sanity test".
The worker's own ``execute_chat_cli`` activity is NOT rewritten to use
ResilientExecutor here — that's Phase 3+.
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

# ``cli_executors.claude`` is the Phase 1.6 public surface. Importing it
# at module load is safe — the lazy ``from workflows import ...`` inside
# ``execute_claude_chat`` keeps workflows.py out of OUR import graph.
from cli_executors.claude import execute_claude_chat

from ._common import (
    binary_on_path,
    map_chat_cli_result_to_execution_result,
    truncate,
)

logger = logging.getLogger(__name__)


@dataclass
class _MinimalChatCliInput:
    """Duck-types ``workflows.ChatCliInput`` for the executor — only the
    fields the executor reads. The adapter shapes its own dataclass so
    we don't have to import workflows.ChatCliInput at the top level
    (which would couple the adapter to the temporal-activity decorator).
    """

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


class ClaudeCodeAdapter:
    name = "claude_code"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        if not binary_on_path("claude"):
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                "`claude` binary not on $PATH",
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
            cli_result = execute_claude_chat(task_input, session_dir)
        except BaseException as exc:  # noqa: BLE001  intentional broad catch
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "ClaudeCodeAdapter.run raised — classified as %s: %s",
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


__all__ = ["ClaudeCodeAdapter"]
