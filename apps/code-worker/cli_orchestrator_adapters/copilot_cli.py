"""CopilotCliAdapter — wraps cli_executors.copilot.execute_copilot_chat.

Phase 2 worker-side ProviderAdapter for the ``copilot_cli`` platform.
The binary on $PATH is ``copilot`` (the GitHub Copilot CLI ships the
binary named ``copilot``, not ``gh-copilot``; the executor's ``cmd =
["copilot", ...]`` confirms it).
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

from cli_executors.copilot import execute_copilot_chat

from cli_orchestrator.preflight import (
    check_binary_on_path,
    check_cloud_api_enabled,
)

from ._common import (
    binary_on_path,
    check_credential_for_platform,
    map_chat_cli_result_to_execution_result,
    time_preflight_helper,
    truncate,
)
from .preflight_deps import PreflightDeps


def _copilot_org_enabled_probe() -> bool:
    """Probe whether GitHub Copilot is enabled for the org.

    Without a token in the worker environment this is a reachability
    check on the GitHub API. The actual "is Copilot enabled for THIS
    org" check requires an org-scoped token — out of scope for the
    worker pod's preflight (the leaf-side `copilot` invocation surfaces
    that error directly via stderr).
    """
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            resp = client.get("https://api.github.com")
            return 200 <= resp.status_code < 500
    except Exception:  # noqa: BLE001
        return False

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


class CopilotCliAdapter:
    name = "copilot_cli"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        # 1. Binary on $PATH
        with time_preflight_helper(self.name, "binary_on_path"):
            br = check_binary_on_path("copilot")
        if not br.ok:
            return br

        # 2. Credentials present
        tenant_id = req.tenant_id or (req.payload or {}).get("tenant_id") or ""
        if tenant_id:
            with time_preflight_helper(self.name, "credentials_present"):
                cr = check_credential_for_platform(
                    PreflightDeps.get(), tenant_id, self.name,
                )
            if not cr.ok:
                return cr

        # 3. Cloud API enabled (org-enabled probe)
        deps = PreflightDeps.get()
        if tenant_id:
            with time_preflight_helper(self.name, "cloud_api_enabled"):
                ar = check_cloud_api_enabled(
                    redis_get=deps.redis_get,
                    redis_setex=deps.redis_setex,
                    probe=_copilot_org_enabled_probe,
                    tenant_id=tenant_id,
                    platform=self.name,
                )
            if not ar.ok:
                return ar

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
            cli_result = execute_copilot_chat(task_input, session_dir)
        except BaseException as exc:  # noqa: BLE001
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "CopilotCliAdapter.run raised — classified as %s: %s",
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


__all__ = ["CopilotCliAdapter"]
