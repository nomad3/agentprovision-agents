"""Worker-side preflight dependency wiring — Phase 3 commit 2.

Provides the ``PreflightDeps`` singleton that lazily wires the
3 expensive closures the canonical preflight helpers consume:

  - ``redis_get`` / ``redis_setex`` — for cloud-API + Temporal-queue
    cache.
  - ``credential_fetch`` — wraps the existing
    ``workflows._fetch_integration_credentials`` HTTP roundtrip.
  - ``heartbeat_probe`` — returns the unix timestamp of the most
    recent worker heartbeat on the ``agentprovision-code`` queue.
    Today this reads a Redis key the worker stamps periodically
    (the same key cli_runtime's heartbeat thread updates).

The closures are intentionally tiny — they exist to keep the
canonical ``cli_orchestrator.preflight`` package free of redis +
httpx + workflows imports. The worker container already has all
three; this module is the seam.

Used by ``_common.check_credential_for_platform`` and the per-adapter
``preflight()`` methods.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class PreflightDeps:
    """Lazy-init singleton for the 3 adapter-side closures.

    Attribute access lazily builds the underlying client / closure on
    first use. Tests inject mocks via ``set_for_test()``.
    """

    _instance: Optional["PreflightDeps"] = None

    def __init__(self) -> None:
        self._redis_client = None
        self._redis_init_failed = False
        self._credential_fetch_override = None
        self._heartbeat_probe_override = None

    # ── Singleton helpers ────────────────────────────────────────────

    @classmethod
    def get(cls) -> "PreflightDeps":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_for_test(cls) -> None:
        cls._instance = None

    def set_for_test(
        self,
        *,
        redis_client=None,
        credential_fetch=None,
        heartbeat_probe=None,
    ) -> None:
        """Inject overrides for tests. Any None field keeps the default."""
        if redis_client is not None:
            self._redis_client = redis_client
            self._redis_init_failed = False
        if credential_fetch is not None:
            self._credential_fetch_override = credential_fetch
        if heartbeat_probe is not None:
            self._heartbeat_probe_override = heartbeat_probe

    # ── Redis client ─────────────────────────────────────────────────

    def _get_redis(self):
        if self._redis_client is not None:
            return self._redis_client
        if self._redis_init_failed:
            return None
        try:
            import redis  # type: ignore
            url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
            client = redis.Redis.from_url(
                url, socket_timeout=0.5, socket_connect_timeout=0.5,
            )
            client.ping()
            self._redis_client = client
            return client
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "preflight: redis unavailable, helpers will degrade (%s)", exc,
            )
            self._redis_init_failed = True
            return None

    def redis_get(self, key: str):
        """Returns bytes|None — None on cache miss OR Redis unreachable."""
        client = self._get_redis()
        if client is None:
            return None
        try:
            return client.get(key)
        except Exception:  # noqa: BLE001
            return None

    def redis_setex(self, key: str, ttl: int, value: str) -> None:
        client = self._get_redis()
        if client is None:
            return
        try:
            client.setex(key, ttl, value)
        except Exception:  # noqa: BLE001
            return

    # ── Credential fetch ─────────────────────────────────────────────

    def credential_fetch(self, platform: str, tenant_id: str):
        """Wraps workflows._fetch_integration_credentials.

        Returns the dict on success, raises on connection failure (the
        canonical helper turns a raised exception into NEEDS_AUTH).
        """
        if self._credential_fetch_override is not None:
            return self._credential_fetch_override(platform, tenant_id)
        # Lazy-import workflows so this module stays importable in test
        # contexts that don't have the full workflow code path wired.
        from workflows import _fetch_integration_credentials  # type: ignore
        return _fetch_integration_credentials(platform, tenant_id)

    # ── Heartbeat probe ──────────────────────────────────────────────

    # Redis key the worker stamps with each heartbeat — design §9.1
    # explicitly says we extend the existing pattern, not introduce a
    # new mechanism. Worker pods write to this key; preflight reads it.
    _HEARTBEAT_KEY = "cli_orchestrator:heartbeat:agentprovision-code"

    def heartbeat_probe(self):
        """Returns unix-ts float of last heartbeat, or None."""
        if self._heartbeat_probe_override is not None:
            return self._heartbeat_probe_override()
        raw = self.redis_get(self._HEARTBEAT_KEY)
        if raw is None:
            return None
        try:
            return float(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
        except (ValueError, TypeError):
            return None


__all__ = ["PreflightDeps"]
