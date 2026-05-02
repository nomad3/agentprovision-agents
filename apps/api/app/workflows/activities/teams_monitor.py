"""Temporal activities for the Teams channel monitor.

The TeamsMonitorWorkflow runs a single activity per tick that delegates
to ``teams_service.monitor_tick`` — keeping all the inbound-DM gating,
allowlist enforcement, idempotent dedup, and Graph token refresh in
one place (the service module).
"""
import asyncio
import logging
from typing import Any, Dict

from temporalio import activity

logger = logging.getLogger(__name__)


# Heartbeat cadence inside a tick. The workflow declares
# heartbeat_timeout=60s; the wrapper sends one every 20s while the
# tick runs so a slow Graph fan-out (busy tenant with many
# `@odata.nextLink` pages) doesn't trip HeartbeatTimeoutError.
# Without this, a long-running tick gets killed mid-flight and the
# cursor never advances — the gap window would be silently lost.
# Reviewer-flagged as Important #1 in PR #250.
_HEARTBEAT_INTERVAL_S = 20


async def _heartbeat_loop(stop_event: asyncio.Event) -> None:
    """Background heartbeat pulse while the main tick runs.

    Stops cleanly when ``stop_event`` is set or on cancellation.
    Tolerates being called outside an activity context (unit tests
    don't enter Temporal's activity scope) — the heartbeat call
    raises and we swallow.
    """
    try:
        while not stop_event.is_set():
            try:
                activity.heartbeat()
            except Exception:
                # Heartbeats outside an activity context throw — fine
                # for unit tests; nothing to do.
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_HEARTBEAT_INTERVAL_S)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        # Caller explicitly cancels us when the main tick returns.
        raise


@activity.defn(name="teams_monitor_tick")
async def teams_monitor_tick(tenant_id: str, account_id: str = "default") -> Dict[str, Any]:
    """Run one Teams Monitor poll for a tenant.

    Wraps ``app.services.teams_service.teams_service.monitor_tick``.
    The service handles credential lookup, Graph fan-out, allowlist
    enforcement, dedup against ``acct.config.processed_ids``, and
    safely returns even when the Teams account is no longer enabled
    (so workflow restarts after a disable don't error out).

    Heartbeats every 20s while the tick is in flight (workflow declares
    heartbeat_timeout=60s) so Graph pagination can run longer than 60s
    without the activity being killed by Temporal.

    Returns the tick result dict; the workflow uses it for logging only.
    """
    # Lazy import keeps temporal worker startup fast — the service
    # pulls in httpx, sqlalchemy, etc.
    from app.services.teams_service import teams_service

    stop = asyncio.Event()
    hb_task = asyncio.create_task(_heartbeat_loop(stop))

    try:
        result = await teams_service.monitor_tick(tenant_id, account_id)
        return result or {"ok": False, "reason": "monitor_tick returned None"}
    except asyncio.CancelledError:
        # Honored by Temporal so the worker can shut down cleanly.
        raise
    except Exception as e:
        # Don't let a single bad tick poison the workflow. Log + return
        # a structured error so the workflow keeps continuing-as-new.
        logger.exception(
            "Teams monitor tick failed for tenant=%s account=%s",
            str(tenant_id)[:8], account_id,
        )
        return {"ok": False, "reason": f"exception: {e!r}"}
    finally:
        # Stop the heartbeat loop and wait briefly for it to wind down.
        stop.set()
        if not hb_task.done():
            try:
                await asyncio.wait_for(hb_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                hb_task.cancel()
            except Exception:
                pass
