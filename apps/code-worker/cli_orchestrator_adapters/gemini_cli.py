"""GeminiCliAdapter — wraps cli_executors.gemini.execute_gemini_chat.

Phase 2 worker-side ProviderAdapter for the ``gemini_cli`` platform.
The executor's positional ``image_path`` matches the codex executor.
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

from cli_executors.gemini import execute_gemini_chat

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


def _gemini_api_probe() -> bool:
    """Probe ``generativelanguage.googleapis.com`` reachability.

    Returns True when the API endpoint is reachable. The actual
    project-level "API enabled" check requires a Google Cloud SDK call
    keyed by the tenant's GCP project — out of scope for the worker
    pod. We use HTTP reachability as the proxy: a 401/403 still means
    the API is enabled (you just don't have creds — that's NEEDS_AUTH,
    handled by check_credentials_present).
    """
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
            )
            # Any 2xx/4xx means the API itself is up. 5xx → treat as
            # disabled / outage.
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


class GeminiCliAdapter:
    name = "gemini_cli"

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        # 1. Binary on $PATH
        with time_preflight_helper(self.name, "binary_on_path"):
            br = check_binary_on_path("gemini")
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

        # 3. Cloud API enabled (Redis-cached, generativelanguage probe)
        deps = PreflightDeps.get()
        if tenant_id:
            with time_preflight_helper(self.name, "cloud_api_enabled"):
                ar = check_cloud_api_enabled(
                    redis_get=deps.redis_get,
                    redis_setex=deps.redis_setex,
                    probe=_gemini_api_probe,
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
            cli_result = execute_gemini_chat(task_input, session_dir, image_path)
        except BaseException as exc:  # noqa: BLE001
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "GeminiCliAdapter.run raised — classified as %s: %s",
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


__all__ = ["GeminiCliAdapter"]
