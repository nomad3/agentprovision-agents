"""CLI platform resolver — autodetect + fallback chain.

Picks which CLI a chat turn should run on, based on:

1. Per-agent ``config.preferred_cli`` override (highest precedence —
   imported Microsoft agents set this to ``copilot_cli``).
2. Tenant ``tenant_features.default_cli_platform`` (admin-set).
3. **Autodetect** from connected integrations — pick whatever the tenant
   actually has credentials for. This is the new behavior: a tenant who
   connected only GitHub Copilot will route to ``copilot_cli`` even
   without setting any explicit default.
4. ``opencode`` (local Gemma 4) as the final floor when nothing else is
   wired and the tenant has no CLI subscription at all.

The resolver returns an *ordered chain*, not a single choice — the
caller (``agent_router.route_and_execute``) walks the chain on
quota/auth failures so a Copilot CLI rate-limit transparently falls
over to Claude Code (or whichever is next available).

Cooldowns
---------

When a CLI returns a quota or auth error, we mark it cool for
``_COOLDOWN_SECONDS`` so subsequent chat turns skip it and go straight
to the fallback. Cooldown lives in Redis (already in the stack); if
Redis is unavailable, the cooldown silently degrades to in-process —
re-trying a rate-limited CLI on every request is annoying but not
fatal, and one failed attempt is still cheaper than no fallback.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.tenant_features import TenantFeatures

logger = logging.getLogger(__name__)


# Default priority when no explicit preference matches. Ordered from
# "most likely paid + most capable" to "local fallback". Adjust here if
# product preferences change — there's no reason to spread this list
# across the codebase.
_DEFAULT_PRIORITY: tuple[str, ...] = (
    "claude_code",
    "copilot_cli",
    "gemini_cli",
    "codex",
    "opencode",
)

_VALID_PLATFORMS: frozenset[str] = frozenset(_DEFAULT_PRIORITY)

# Map CLI platform → integration_names that, when connected, prove the
# CLI can authenticate. ``opencode`` runs locally (no integration).
# Order within each tuple matters only for diagnostics — any one match
# is sufficient.
_CLI_TO_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "claude_code": ("claude_code",),
    "copilot_cli": ("github",),
    "codex": ("codex",),
    "gemini_cli": ("gemini_cli", "gmail", "google_drive", "google_calendar"),
    "opencode": (),  # local
}

_COOLDOWN_SECONDS = int(os.environ.get("CLI_COOLDOWN_SECONDS", "600"))

# Process-local fallback when Redis is unavailable. Survives the worker
# lifetime (good enough — Temporal restart resets it).
_local_cooldown: dict[str, float] = {}


def _redis_client():
    """Lazy Redis client. Returns None if Redis isn't reachable so the
    resolver degrades gracefully to the in-process dict.
    """
    try:
        import redis  # type: ignore
        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        # Trip an immediate failure rather than waiting for the first
        # operation if Redis is down.
        client.ping()
        return client
    except Exception:
        return None


def _cooldown_key(tenant_id, platform: str) -> str:
    return f"cli_cooldown:{tenant_id}:{platform}"


def is_in_cooldown(tenant_id, platform: str) -> bool:
    """Return True if this CLI was recently quota'd / auth-failed."""
    key = _cooldown_key(tenant_id, platform)
    redis = _redis_client()
    if redis is not None:
        try:
            return bool(redis.exists(key))
        except Exception:
            pass
    expires_at = _local_cooldown.get(key)
    if expires_at is None:
        return False
    if expires_at < time.time():
        _local_cooldown.pop(key, None)
        return False
    return True


def mark_cooldown(tenant_id, platform: str, *, reason: str = "") -> None:
    """Mark this (tenant, platform) pair cool for ``_COOLDOWN_SECONDS``."""
    if platform not in _VALID_PLATFORMS or platform == "opencode":
        # Don't cool down the local floor — it's the universal fallback.
        return
    key = _cooldown_key(tenant_id, platform)
    redis = _redis_client()
    if redis is not None:
        try:
            redis.setex(key, _COOLDOWN_SECONDS, reason or "1")
            logger.info(
                "CLI cooldown set: tenant=%s platform=%s ttl=%ds reason=%s",
                str(tenant_id)[:8], platform, _COOLDOWN_SECONDS, reason or "n/a",
            )
            return
        except Exception:
            pass
    _local_cooldown[key] = time.time() + _COOLDOWN_SECONDS
    logger.info(
        "CLI cooldown set (local fallback): tenant=%s platform=%s ttl=%ds reason=%s",
        str(tenant_id)[:8], platform, _COOLDOWN_SECONDS, reason or "n/a",
    )


# Patterns that mean "this CLI can't process this turn — try the next
# one." Matched against the metadata.error string from run_agent_session.
# Conservative on purpose: false-negative (no retry on quota) is
# acceptable; false-positive (retry on user-content errors) wastes the
# user's CLI quota.
_QUOTA_PATTERNS = re.compile(
    r"(quota[\s_-]?(exceeded|exhausted|limit)|rate[\s_-]?limit|insufficient[\s_-]?(quota|credit)|"
    r"credit[\s_-]?balance|out of (tokens|credits|quota)|too many requests|429)",
    re.IGNORECASE,
)
_AUTH_PATTERNS = re.compile(
    r"(unauthorized|invalid[\s_-]?(grant|token)|token[\s_-]?(expired|invalid)|401|403|"
    r"authentication[\s_-]?failed|subscription is not connected|not connected.*integration)",
    re.IGNORECASE,
)


def classify_error(error: Optional[str]) -> Optional[str]:
    """Return ``"quota"`` | ``"auth"`` | None.

    Only "quota" and "auth" trigger fallback; everything else is treated
    as a real failure and bubbles up. ``None`` input → ``None``.
    """
    if not error:
        return None
    if _QUOTA_PATTERNS.search(error):
        return "quota"
    if _AUTH_PATTERNS.search(error):
        return "auth"
    return None


def _connected_clis(db: Session, tenant_id: uuid.UUID) -> set[str]:
    """Which CLI platforms does this tenant have credentials for?"""
    # Lazy import to avoid a circular import via integration_status →
    # integration_credential models at module-load time.
    from app.services.integration_status import get_connected_integrations

    try:
        connected_map = get_connected_integrations(db, tenant_id)
    except Exception as e:
        logger.warning(
            "CLI resolver: get_connected_integrations failed for tenant=%s: %s — "
            "assuming no integrations connected",
            str(tenant_id)[:8], e,
        )
        connected_map = {}

    connected_names = {
        name for name, info in (connected_map or {}).items()
        if isinstance(info, dict) and info.get("connected")
    }

    available: set[str] = {"opencode"}  # local always works
    for cli, integrations in _CLI_TO_INTEGRATIONS.items():
        if not integrations:
            continue
        if any(name in connected_names for name in integrations):
            available.add(cli)
    return available


def resolve_cli_chain(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    explicit_platform: Optional[str] = None,
    skip_cooldown: bool = False,
) -> List[str]:
    """Return the ordered list of CLI platforms to try for this turn.

    ``explicit_platform`` is the per-agent / per-tenant preference (the
    output of the existing override resolution in agent_router). It
    becomes the head of the chain *if* the tenant actually has the
    credentials for it; otherwise it's dropped and the chain is built
    purely from autodetect.

    Cooldown'd platforms are filtered out unless ``skip_cooldown`` is
    True (used by tests). The local ``opencode`` floor is always last.
    """
    available = _connected_clis(db, tenant_id)

    # Build priority order: explicit choice first if it's actually
    # available; then default priority; opencode last (always).
    chain: List[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        if p in seen or p not in _VALID_PLATFORMS:
            return
        if p not in available:
            return
        if not skip_cooldown and is_in_cooldown(tenant_id, p):
            return
        chain.append(p)
        seen.add(p)

    if explicit_platform:
        _add(explicit_platform)

    for p in _DEFAULT_PRIORITY:
        if p == "opencode":
            continue  # always last
        _add(p)

    # opencode is the universal floor — never filtered by cooldown,
    # never absent, always last in the chain so a tenant with zero
    # subscriptions can still get a (degraded) reply.
    if "opencode" not in seen:
        chain.append("opencode")

    return chain
