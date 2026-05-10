"""TemporalActivityAdapter — api-side adapter that dispatches ChatCliWorkflow.

This is the api-side bridge. It implements ``ProviderAdapter`` and
proxies into the existing ``ChatCliWorkflow`` (Temporal workflow on
the ``agentprovision-code`` queue) via a stock ``temporalio.client``
``execute_workflow`` call. Logic lifted from
``cli_session_manager.py:_run_workflow`` (the inner helper at lines
985-1049 prior to Phase 2). The hot-path flag-OFF caller still goes
through the legacy seam in ``cli_session_manager.run_agent_session``;
this adapter is only used when the resilient executor is on.

**Lazy temporalio import.** ``temporalio.client.Client`` is imported
INSIDE ``run()``, never at module load. The api container ships
``temporalio`` but the worker container also imports this adapter via
the canonical package — and the worker's worker-side adapters NEVER
dispatch through this adapter (they call into ``cli_executors.<plat>.
execute_<plat>_chat`` directly). Keeping the import lazy keeps module
load cheap and isolates the Temporal-SDK dependency.

The adapter classifies failures via ``cli_orchestrator.classify`` —
including the temporalio.exceptions.{ApplicationError, ActivityError}
and asyncio.CancelledError → ``Status.WORKFLOW_FAILED`` mapping.
``workflow_id`` and ``activity_id`` are populated from the workflow
handle so callers can drill into the Temporal UI.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta
from typing import Optional

from ..classifier import classify
from ..redaction import redact
from ..status import Status
from .base import ExecutionRequest, ExecutionResult, PreflightResult

logger = logging.getLogger(__name__)


# 4KB stdout/stderr cap — matches design §4 (redacted, max 4KB).
_SUMMARY_MAX_BYTES = 4096


# --------------------------------------------------------------------------
# Phase 3 commit 2 — Temporal queue heartbeat-staleness probe
# --------------------------------------------------------------------------

_QUEUE_PROBE_OVERRIDE: Optional[tuple] = None
"""Tests inject (redis_get, redis_setex, hb_probe) here to bypass Redis."""


def _resolve_queue_probe_closures():
    """Return ``(redis_get, redis_setex, hb_probe)`` closures.

    Defaults to a Redis-backed implementation reading the same
    ``cli_orchestrator:heartbeat:agentprovision-code`` key the worker
    stamps. On Redis unavailability or any error the closures degrade
    to no-op / None (the canonical helper handles that as
    ``PROVIDER_UNAVAILABLE``).
    """
    if _QUEUE_PROBE_OVERRIDE is not None:
        return _QUEUE_PROBE_OVERRIDE

    _redis_singleton = None

    def _client():
        nonlocal _redis_singleton
        if _redis_singleton is not None:
            return _redis_singleton
        try:
            import redis as redis_lib  # type: ignore
            url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
            client = redis_lib.Redis.from_url(
                url, socket_timeout=0.5, socket_connect_timeout=0.5,
            )
            client.ping()
            _redis_singleton = client
            return client
        except Exception:  # noqa: BLE001
            return None

    def redis_get(k):
        c = _client()
        if c is None:
            return None
        try:
            return c.get(k)
        except Exception:  # noqa: BLE001
            return None

    def redis_setex(k, ttl, v):
        c = _client()
        if c is None:
            return
        try:
            c.setex(k, ttl, v)
        except Exception:  # noqa: BLE001
            return

    def hb_probe():
        c = _client()
        if c is None:
            return None
        try:
            raw = c.get("cli_orchestrator:heartbeat:agentprovision-code")
        except Exception:  # noqa: BLE001
            return None
        if raw is None:
            return None
        try:
            return float(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
        except (ValueError, TypeError):
            return None

    return (redis_get, redis_setex, hb_probe)


def _truncate(text: str) -> str:
    if not text:
        return ""
    if len(text) <= _SUMMARY_MAX_BYTES:
        return text
    return text[:_SUMMARY_MAX_BYTES] + "\n…(truncated)"


class TemporalActivityAdapter:
    """Dispatches a ``ChatCliWorkflow`` for one platform.

    Args:
        platform: The CLI platform name. Used both as the adapter
            ``name`` (for routing/metrics) and as the ``platform``
            field on the dispatched ``ChatCliInput``.
        temporal_address: Optional override; defaults to env
            ``TEMPORAL_ADDRESS`` then ``temporal:7233``.
        execution_timeout_minutes: Workflow execution timeout. Default
            180 mirrors the legacy seam.
    """

    def __init__(
        self,
        platform: str,
        *,
        temporal_address: Optional[str] = None,
        execution_timeout_minutes: int = 180,
    ) -> None:
        self.name = platform
        self._platform = platform
        self._temporal_address = temporal_address
        self._execution_timeout_minutes = execution_timeout_minutes

    # ── Protocol surface ─────────────────────────────────────────────

    def preflight(self, req: ExecutionRequest) -> PreflightResult:
        """Phase 3 preflight: SDK importable + heartbeat-staleness probe.

        Per design §6 row 5 + plan §2.3: heartbeat-staleness, NOT
        ``describe_task_queue``. The probe reads a Redis key the
        worker stamps periodically; a stale or absent heartbeat
        returns ``PROVIDER_UNAVAILABLE``.

        On the api-side dispatcher path the closure is wired here once
        per process (lazy Redis client). Tests inject overrides via
        the module-level ``_QUEUE_PROBE_OVERRIDE`` hook.
        """
        try:
            import temporalio.client  # noqa: F401
        except ImportError:
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                "temporalio SDK not installed",
            )
        # Heartbeat-staleness check — design §6 row 5.
        try:
            from ..preflight import check_temporal_queue_reachable
            from . import temporal_activity as _self_mod
            redis_get, redis_setex, hb_probe = _resolve_queue_probe_closures()
            return check_temporal_queue_reachable(
                redis_get=redis_get,
                redis_setex=redis_setex,
                heartbeat_probe=hb_probe,
            )
        except Exception:  # noqa: BLE001
            # Probe wiring failure is non-fatal — fall through to
            # OK so dispatch can still attempt (and surface a clearer
            # error if Temporal is genuinely down). Phase 3: prefer
            # availability of the chat path over failing closed.
            return PreflightResult.succeed()

    def classify_error(
        self,
        stderr: Optional[str],
        exit_code: Optional[int],
        exc: Optional[BaseException],
    ) -> Status:
        return classify(stderr, exit_code, exc)

    def run(self, req: ExecutionRequest) -> ExecutionResult:
        """Dispatch ChatCliWorkflow and shape the result into ExecutionResult.

        Never raises. On any exception path we classify and return.
        """
        # Lazy temporalio import — sandbox safety. apps/api ships the SDK,
        # but importing at module load would make this module unimportable
        # in environments missing the SDK (e.g. tests against the public
        # cli_orchestrator package without temporalio installed).
        import asyncio
        import concurrent.futures
        from dataclasses import dataclass as _dc

        run_id = req.run_id or str(uuid.uuid4())
        workflow_id = f"chat-cli-{uuid.uuid4()}"
        platform_attempted = [self._platform]

        temporal_address = self._temporal_address or os.environ.get(
            "TEMPORAL_ADDRESS", "temporal:7233"
        )

        payload = req.payload or {}
        message = payload.get("message", "")
        tenant_id = req.tenant_id or payload.get("tenant_id", "")

        @_dc
        class _ChatCliInput:
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

        task_input = _ChatCliInput(
            platform=self._platform,
            message=message,
            tenant_id=str(tenant_id),
            instruction_md_content=payload.get("instruction_md_content", ""),
            mcp_config=payload.get("mcp_config", ""),
            image_b64=payload.get("image_b64", ""),
            image_mime=payload.get("image_mime", ""),
            session_id=payload.get("session_id", ""),
            model=payload.get("model", ""),
            allowed_tools=payload.get("allowed_tools", ""),
        )

        async def _run_workflow():
            from temporalio.client import Client as TemporalClient

            client = await TemporalClient.connect(temporal_address)
            return await client.execute_workflow(
                "ChatCliWorkflow",
                task_input,
                id=workflow_id,
                task_queue="agentprovision-code",
                execution_timeout=timedelta(minutes=self._execution_timeout_minutes),
            )

        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is not None and running_loop.is_running():
                # Already inside an async context — run the workflow in a
                # separate thread with its own event loop. Mirrors the
                # legacy seam from cli_session_manager.
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    workflow_result = pool.submit(
                        lambda: asyncio.run(_run_workflow())
                    ).result(timeout=600)
            else:
                workflow_result = asyncio.run(_run_workflow())
        except BaseException as exc:  # noqa: BLE001  intentional broad catch
            # Classify and return — never raise. Catches:
            # asyncio.CancelledError, temporalio.exceptions.*,
            # subprocess.TimeoutExpired bubbling, etc.
            status = self.classify_error(stderr=None, exit_code=None, exc=exc)
            err_redacted = redact(str(exc) or exc.__class__.__name__)
            logger.warning(
                "TemporalActivityAdapter.run dispatch failure platform=%s status=%s",
                self._platform, status.value,
            )
            return ExecutionResult(
                status=status,
                platform=self._platform,
                response_text="",
                error_message=err_redacted,
                stderr_summary=_truncate(err_redacted),
                platform_attempted=platform_attempted,
                attempt_count=1,
                workflow_id=workflow_id,
                run_id=run_id,
            )

        # Workflow executed — pull response_text/success/error/metadata
        if isinstance(workflow_result, dict):
            success = workflow_result.get("success", False)
            response_text = workflow_result.get("response_text", "") or ""
            error = workflow_result.get("error")
            meta = workflow_result.get("metadata") or {}
        else:
            success = getattr(workflow_result, "success", False)
            response_text = getattr(workflow_result, "response_text", "") or ""
            error = getattr(workflow_result, "error", None)
            meta = getattr(workflow_result, "metadata", None) or {}

        if success and response_text:
            redacted_text = redact(response_text)
            return ExecutionResult(
                status=Status.EXECUTION_SUCCEEDED,
                platform=self._platform,
                response_text=redacted_text,
                stdout_summary=_truncate(redacted_text),
                exit_code=0,
                platform_attempted=platform_attempted,
                attempt_count=1,
                workflow_id=workflow_id,
                metadata=dict(meta) if isinstance(meta, dict) else {},
                run_id=run_id,
            )

        # Workflow returned but indicated failure — classify the error string.
        err_text = error or "CLI workflow returned empty response"
        status = self.classify_error(
            stderr=err_text, exit_code=None, exc=None
        )
        err_redacted = redact(err_text)
        return ExecutionResult(
            status=status,
            platform=self._platform,
            response_text="",
            error_message=err_redacted,
            stderr_summary=_truncate(err_redacted),
            platform_attempted=platform_attempted,
            attempt_count=1,
            workflow_id=workflow_id,
            metadata=dict(meta) if isinstance(meta, dict) else {},
            run_id=run_id,
        )


__all__ = ["TemporalActivityAdapter"]
