"""Worker-side tenant feature-flag lookup.

The code-worker has no DB credentials by design, so it can't read
`tenant_features` directly. Instead it queries an internal HTTPS
endpoint with the shared `X-Internal-Key` — same pattern as
``_fetch_github_token`` / ``_fetch_claude_token``.

Results are cached per-process for 60s to bound the per-chat-turn
overhead at ≤1 request per minute per tenant.

Used by the Claude executor to gate the `--output-format stream-json`
rollout (plan §9) — default OFF prod, ON for the saguilera test
tenant.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict, Tuple

import httpx

logger = logging.getLogger(__name__)


_CACHE_TTL_SECONDS = 60.0
# tenant_id → (timestamp, flag_dict)
_cache: Dict[str, Tuple[float, Dict[str, bool]]] = {}
_cache_lock = threading.Lock()


def _fetch_flags(tenant_id: str) -> Dict[str, bool]:
    """Fetch the tenant-features blob from the API. Fail-soft → {}."""
    base = os.environ.get("API_BASE_URL", "http://agentprovision-api").rstrip("/")
    key = os.environ.get("API_INTERNAL_KEY", "")
    # Route is `/api/v1/features` (router prefix) + `/internal/tenant-features/{id}`
    # — keeps the v1 features router as the single source of truth for
    # tenant_features projection without introducing a new top-level
    # mount.
    url = f"{base}/api/v1/features/internal/tenant-features/{tenant_id}"
    try:
        with httpx.Client(timeout=2.0) as c:
            resp = c.get(url, headers={"X-Internal-Key": key or "dev_internal_key"})
            if resp.status_code != 200:
                return {}
            data = resp.json() or {}
            # Coerce common bool fields to native bools so callers don't
            # have to type-check.
            return {k: bool(v) for k, v in data.items() if isinstance(v, (bool, int))}
    except Exception:  # noqa: BLE001
        return {}


def is_enabled(tenant_id: str, flag: str, *, default: bool = False) -> bool:
    """Return True iff the named feature flag is True for this tenant.

    Fail-soft: if the API is unreachable or the tenant has no row,
    returns ``default``. Result is cached for 60s per tenant.
    """
    if not tenant_id:
        return default
    now = time.time()
    with _cache_lock:
        cached = _cache.get(tenant_id)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return bool(cached[1].get(flag, default))
    flags = _fetch_flags(tenant_id)
    with _cache_lock:
        _cache[tenant_id] = (now, flags)
    return bool(flags.get(flag, default))


def reset_cache() -> None:
    """Test helper — drop the per-tenant cache."""
    with _cache_lock:
        _cache.clear()
