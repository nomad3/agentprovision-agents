"""Preflight shared helpers — design §6.

Five callable-injection helpers each adapter composes for its
``preflight()`` method. Callable injection (``fetch=...``,
``redis_get=...``, etc.) keeps the canonical
``cli_orchestrator`` package free of redis / temporalio / vault
imports at module load: the helper bodies use ONLY their injected
callables, and the worker / api adapter side wires those closures
in once at process start.

Latency budgets (design §6 table):

  - ``check_binary_on_path``                 < 1ms (memoised which)
  - ``check_workspace_trust_file``           < 1ms (stat + cached)
  - ``check_credentials_present``            < 5ms (vault hot path)
  - ``check_cloud_api_enabled``              < 50ms uncached / < 1ms cached
  - ``check_temporal_queue_reachable``       < 10ms (heartbeat-cache)

A new ``cli_orchestrator_preflight_duration_ms`` Histogram is added in
``executor.py`` (commit 1 in Phase 3) and timed by adapters that want
to expose per-helper latency. The helpers themselves do NOT emit the
metric — that's the adapter's job (the helper has no notion of
``decision_point`` / ``platform`` labels).
"""
from __future__ import annotations

import logging
import shutil
import os
from pathlib import Path
from typing import Callable, Optional

from .adapters.base import PreflightResult
from .status import Status

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Module-level memoisation caches
# --------------------------------------------------------------------------

# ``shutil.which`` result memo. Worker pods cycle on deploy so a stale
# "not present" memo gets washed out by the next deploy. Test code
# clears this via ``clear_caches()`` below.
_WHICH_CACHE: dict[str, Optional[str]] = {}

# Workspace trust file existence + mtime memo. Keyed by absolute path
# string; the value is a tuple of (exists, mtime_ns) cached for the
# lifetime of the process.
_TRUST_FILE_CACHE: dict[str, bool] = {}


def clear_caches() -> None:
    """Test-only — wipe all preflight memo caches."""
    _WHICH_CACHE.clear()
    _TRUST_FILE_CACHE.clear()


# --------------------------------------------------------------------------
# Helper 1 — binary on $PATH
# --------------------------------------------------------------------------

def check_binary_on_path(name: str) -> PreflightResult:
    """Memoised ``shutil.which`` — design §6 row 1.

    Returns ``PROVIDER_UNAVAILABLE`` on miss. Memoised at the process
    level so steady-state cost is a dict lookup. Worker pods cycle on
    deploy.

    Args:
        name: Binary name (e.g. ``"claude"``, ``"codex"``, ``"gemini"``).
    """
    if name not in _WHICH_CACHE:
        _WHICH_CACHE[name] = shutil.which(name)
    if _WHICH_CACHE[name] is None:
        return PreflightResult.fail(
            Status.PROVIDER_UNAVAILABLE,
            f"`{name}` binary not on $PATH",
        )
    return PreflightResult.succeed()


# --------------------------------------------------------------------------
# Helper 2 — workspace trust file
# --------------------------------------------------------------------------

def check_workspace_trust_file(path: str) -> PreflightResult:
    """``stat`` cache — design §6 row 3.

    The presence of a workspace trust marker file (e.g. Codex
    ``~/.codex/config.toml``, Gemini workspace setup file) is a stable
    artefact: if it's there at process start it stays there. We
    memoise the existence check so steady-state is one dict lookup.

    Returns ``WORKSPACE_UNTRUSTED`` on miss.
    """
    expanded = os.path.expanduser(path)
    if expanded in _TRUST_FILE_CACHE:
        present = _TRUST_FILE_CACHE[expanded]
    else:
        try:
            present = Path(expanded).exists()
        except OSError:
            present = False
        _TRUST_FILE_CACHE[expanded] = present

    if not present:
        return PreflightResult.fail(
            Status.WORKSPACE_UNTRUSTED,
            f"workspace trust file missing: {expanded}",
        )
    return PreflightResult.succeed()


# --------------------------------------------------------------------------
# Helper 3 — credentials present
# --------------------------------------------------------------------------

def check_credentials_present(
    *,
    fetch: Callable[[str, str], Optional[dict]],
    tenant_id: str,
    platform: str,
) -> PreflightResult:
    """Vault credential fetch — design §6 row 2.

    The ``fetch`` callable maps ``(integration_name, tenant_id) ->
    Optional[dict]``. A ``None`` or empty-dict return is treated as
    NEEDS_AUTH. The callable is responsible for any caching; the
    helper is a pure adapter between the executor's preflight contract
    and the existing vault hot path.

    Args:
        fetch: callable (integration_name, tenant_id) -> dict | None
        tenant_id: tenant uuid as a string
        platform: CLI platform name (claude_code / codex / gemini_cli /
            copilot_cli) — used both as the integration_name and the
            error string.
    """
    try:
        creds = fetch(platform, tenant_id)
    except BaseException as exc:  # noqa: BLE001
        # Vault errors classify as NEEDS_AUTH for preflight purposes —
        # the user must reconnect the integration. Don't poison the
        # chain; the chain walker will fall through.
        logger.debug(
            "credential fetch raised — preflight=NEEDS_AUTH platform=%s: %s",
            platform, exc,
        )
        return PreflightResult.fail(
            Status.NEEDS_AUTH,
            f"credential fetch failed for {platform}: {exc.__class__.__name__}",
        )
    if not creds:
        return PreflightResult.fail(
            Status.NEEDS_AUTH,
            f"no credentials for {platform}",
        )
    return PreflightResult.succeed()


# --------------------------------------------------------------------------
# Helper 4 — cloud API enabled (Redis-cached)
# --------------------------------------------------------------------------

def check_cloud_api_enabled(
    *,
    redis_get: Callable[[str], Optional[bytes]],
    redis_setex: Callable[[str, int, str], None],
    probe: Callable[[], bool],
    tenant_id: str,
    platform: str,
    ttl_seconds: int = 300,
) -> PreflightResult:
    """Cloud-API gate with Redis cache — design §6 row 4.

    On cache hit returns immediately. On cache miss runs ``probe()``
    (which the adapter wires to the actual GCP / GitHub Copilot org
    check) and caches the result for ``ttl_seconds``.

    A True result is cached as ``"1"``; a False result is cached as
    ``"0"`` so we don't re-probe a known-disabled API every preflight.
    Cached "0" still returns API_DISABLED.

    Args:
        redis_get: callable (key) -> bytes|None — None on cache miss
            OR Redis unavailable.
        redis_setex: callable (key, ttl, value) -> None.
        probe: callable () -> bool — True if API is enabled.
        tenant_id: tenant uuid as a string (cache key component).
        platform: CLI platform name (cache key component).
        ttl_seconds: cache TTL. Default 300s mirrors design §6.

    Returns:
        OK on enabled API; ``API_DISABLED`` on disabled.
    """
    key = f"cli_orchestrator:preflight:cloud_api:{tenant_id}:{platform}"
    try:
        cached = redis_get(key)
    except BaseException:  # noqa: BLE001
        cached = None  # Redis hiccup → degrade to probe.

    if cached is not None:
        try:
            value = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
        except Exception:  # noqa: BLE001
            value = ""
        if value == "1":
            return PreflightResult.succeed()
        if value == "0":
            return PreflightResult.fail(
                Status.API_DISABLED,
                f"{platform} cloud API disabled (cached)",
            )
        # Unknown cache value — fall through to probe.

    try:
        ok = bool(probe())
    except BaseException as exc:  # noqa: BLE001
        # A probe failure is treated as API_DISABLED (the user must
        # check their console). Don't poison the chain.
        logger.debug(
            "cloud-api probe raised — preflight=API_DISABLED platform=%s: %s",
            platform, exc,
        )
        try:
            redis_setex(key, ttl_seconds, "0")
        except BaseException:  # noqa: BLE001
            pass
        return PreflightResult.fail(
            Status.API_DISABLED,
            f"{platform} cloud API probe failed: {exc.__class__.__name__}",
        )

    try:
        redis_setex(key, ttl_seconds, "1" if ok else "0")
    except BaseException:  # noqa: BLE001
        pass

    if ok:
        return PreflightResult.succeed()
    return PreflightResult.fail(
        Status.API_DISABLED,
        f"{platform} cloud API disabled",
    )


# --------------------------------------------------------------------------
# Helper 5 — Temporal queue reachable (heartbeat-staleness flavour)
# --------------------------------------------------------------------------

def check_temporal_queue_reachable(
    *,
    redis_get: Callable[[str], Optional[bytes]],
    redis_setex: Callable[[str, int, str], None],
    heartbeat_probe: Callable[[], Optional[float]],
    queue_name: str = "agentprovision-code",
    ttl_seconds: int = 30,
) -> PreflightResult:
    """Temporal queue reachability via heartbeat-staleness — design §6 row 5.

    Plan §2.3 explicitly says: heartbeat-staleness, NOT
    ``describe_task_queue``. The intent is "is there a recent
    heartbeat from a worker on this queue?" — answered by an existing
    Redis key the worker pod stamps periodically. If the heartbeat is
    older than ``2 * heartbeat_interval`` (or absent), we return
    PROVIDER_UNAVAILABLE.

    The ``heartbeat_probe`` callable returns the unix timestamp of
    the last heartbeat, or ``None`` if no heartbeat is on record.

    Args:
        redis_get: callable (key) -> bytes|None for the cached
            verdict (set after an uncached probe).
        redis_setex: callable (key, ttl, value) -> None.
        heartbeat_probe: callable () -> float|None — last-seen unix ts.
        queue_name: Temporal task queue. Default ``agentprovision-code``.
        ttl_seconds: cache TTL on the verdict. Default 30s.

    Returns:
        OK when a recent heartbeat is present; otherwise
        ``PROVIDER_UNAVAILABLE``.
    """
    key = f"cli_orchestrator:preflight:temporal_queue:{queue_name}"
    try:
        cached = redis_get(key)
    except BaseException:  # noqa: BLE001
        cached = None

    if cached is not None:
        try:
            value = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
        except Exception:  # noqa: BLE001
            value = ""
        if value == "1":
            return PreflightResult.succeed()
        if value == "0":
            return PreflightResult.fail(
                Status.PROVIDER_UNAVAILABLE,
                f"temporal queue {queue_name} stale (cached)",
            )

    # Heartbeat-staleness: query the probe; if older than 2*interval (proxy
    # default 60s for a 30s interval) treat as stale.
    import time as _time
    try:
        last_seen = heartbeat_probe()
    except BaseException as exc:  # noqa: BLE001
        logger.debug(
            "heartbeat probe raised — preflight=PROVIDER_UNAVAILABLE queue=%s: %s",
            queue_name, exc,
        )
        last_seen = None

    fresh = False
    if last_seen is not None:
        try:
            age = _time.time() - float(last_seen)
            # 60s = 2 * default heartbeat_interval (30s) per cli_runtime.
            fresh = age >= 0 and age <= 60
        except (TypeError, ValueError):
            fresh = False

    try:
        redis_setex(key, ttl_seconds, "1" if fresh else "0")
    except BaseException:  # noqa: BLE001
        pass

    if fresh:
        return PreflightResult.succeed()
    return PreflightResult.fail(
        Status.PROVIDER_UNAVAILABLE,
        f"temporal queue {queue_name}: no recent worker heartbeat",
    )


__all__ = [
    "check_binary_on_path",
    "check_workspace_trust_file",
    "check_credentials_present",
    "check_cloud_api_enabled",
    "check_temporal_queue_reachable",
    "clear_caches",
]
