"""BrightLocal SEO MCP tools.

Wraps the BrightLocal Local Search Rank Checker (LSRC) API. Powers the daily
SEO Sentinel workflow on the Animal Doctor SOC tenant (and any other tenant
that connects BrightLocal).

API surface:
- ``brightlocal_list_keywords`` — pull tracked keywords for the tenant's account
- ``brightlocal_get_rankings`` — current SERP positions for a keyword (or all)
- ``brightlocal_rank_changes`` — diff vs N days ago
- ``brightlocal_competitor_check`` — competitor positions on tracked keywords

BrightLocal authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~
Every request needs three params: ``api-key``, ``sig``, ``expires``.

* ``expires`` — unix timestamp (UTC), max 30 minutes in the future
* ``sig``    — base64(HMAC-SHA1(api_key + expires, api_secret))

We sign every request fresh; signatures are never cached. Credentials live
in the credential vault under integration ``brightlocal`` with keys
``api_key`` and ``api_secret`` (the helper supports a single ``api_key``
field too — older agencies share a single combined key/secret).

Caching
~~~~~~~
Rank-tracker results are stable within a day. To avoid burning the BrightLocal
quota (300 GET / minute account-wide) when a workflow polls multiple keywords
in a tight loop, every read is cached in Redis for 4h. Pass
``force_refresh=True`` to bypass the cache.

If Redis is unavailable the tools degrade silently (no cache, but still work).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)

# BrightLocal API base — confirmed via the official PHP/C# helpers
# (https://github.com/BrightLocal/BrightLocal-API-Helper) and the developer
# docs at https://apidocs.brightlocal.com/.
BRIGHTLOCAL_BASE_URL = "https://tools.brightlocal.com/seo-tools/api"
BRIGHTLOCAL_LSRC_PREFIX = "/v2/lsrc"

# 4-hour cache for rank-tracker reads. Daily SEO sentinel runs once per day,
# so this guarantees one upstream call per (tenant, keyword set) per day plus
# headroom for ad-hoc Luna queries within a workshift.
DEFAULT_CACHE_TTL_SECONDS = 4 * 60 * 60

# Signature `expires` window. BrightLocal allows up to 1800s; we use 300s
# so signatures stay fresh and clock skew is bounded.
SIG_EXPIRES_WINDOW_SECONDS = 300


# ---------------------------------------------------------------------------
# Helpers — config + credential vault
# ---------------------------------------------------------------------------


def _get_api_base_url() -> str:
    from src.config import settings

    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings

    return settings.API_INTERNAL_KEY


async def _get_brightlocal_credentials(tenant_id: str) -> Optional[dict]:
    """Retrieve BrightLocal credentials from the vault for this tenant."""
    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v1/oauth/internal/token/brightlocal",
                headers={"X-Internal-Key": internal_key},
                params={"tenant_id": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("brightlocal credential retrieval returned %s", resp.status_code)
    except Exception:
        logger.exception("Failed to retrieve brightlocal credentials")
    return None


# ---------------------------------------------------------------------------
# Helpers — signed request
# ---------------------------------------------------------------------------


def _sign_request(api_key: str, api_secret: str, expires_ts: int) -> str:
    """Generate the BrightLocal signature.

    Pattern (from the official PHP wrapper):
        sig = base64( HMAC-SHA1( api_key + str(expires), api_secret ) )
    """
    payload = f"{api_key}{expires_ts}".encode("utf-8")
    digest = hmac.new(api_secret.encode("utf-8"), payload, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_auth_params(api_key: str, api_secret: str) -> Dict[str, str]:
    expires_ts = int(time.time()) + SIG_EXPIRES_WINDOW_SECONDS
    return {
        "api-key": api_key,
        "sig": _sign_request(api_key, api_secret, expires_ts),
        "expires": str(expires_ts),
    }


def _extract_credentials(creds: dict) -> Optional[Dict[str, str]]:
    """Pull the api_key + api_secret out of a vault payload.

    BrightLocal's official API requires distinct ``api_key`` + ``api_secret``
    (verified against their published spec). We accept the camelCase alias
    ``apiSecret`` and the bare ``secret`` alias as ergonomic helpers, but if
    only ``api_key`` is supplied without a matching secret we fall back to
    using the key itself as the secret.

    NOTE: that single-key fallback is best-effort. It is NOT documented by
    BrightLocal as an officially-supported flow — it only works for the
    rare case where the operator literally entered the same value into both
    fields. If signing fails with INVALID_API_KEY in production, the most
    likely fix is to add a separate ``api_secret`` from the BrightLocal API
    settings page (https://tools.brightlocal.com/seo-tools/api/) rather
    than rely on this fallback. Logged loudly so operators notice.
    """
    if not creds:
        return None
    api_key = creds.get("api_key") or creds.get("apiKey")
    api_secret = creds.get("api_secret") or creds.get("apiSecret") or creds.get("secret")
    account_id = creds.get("account_id") or creds.get("accountId")
    if not api_key:
        return None
    if not api_secret:
        logger.warning(
            "BrightLocal credentials: api_secret missing — falling back to "
            "api_key as the signing secret. This works only when the "
            "operator entered the same value in both fields. If signing "
            "fails with INVALID_API_KEY, supply a separate api_secret from "
            "the BrightLocal API settings page."
        )
    return {
        "api_key": api_key,
        "api_secret": api_secret or api_key,
        "account_id": account_id or "",
    }


# ---------------------------------------------------------------------------
# Helpers — Redis cache (degrades to no-op on failure)
# ---------------------------------------------------------------------------


_redis_client = None  # lazy — set on first use, may stay None forever
_redis_init_attempted = False


def _get_redis():
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    try:
        import redis  # type: ignore

        url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        _redis_client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        # Ping once so we fail fast and degrade rather than time out per-call.
        _redis_client.ping()
        logger.info("brightlocal: redis cache enabled at %s", url)
    except Exception as exc:
        logger.info("brightlocal: redis cache unavailable (%s); running uncached", exc)
        _redis_client = None
    return _redis_client


def _cache_key(tenant_id: str, suffix: str) -> str:
    return f"brightlocal:{tenant_id}:{suffix}"


def _cache_get(key: str) -> Optional[dict]:
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("brightlocal: cache read failed for %s", key)
        return None


def _cache_set(key: str, value: dict, ttl: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        logger.exception("brightlocal: cache write failed for %s", key)


# ---------------------------------------------------------------------------
# Helpers — upstream HTTP
# ---------------------------------------------------------------------------


async def _brightlocal_get(
    path: str,
    auth_params: Dict[str, str],
    extra_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Issue a signed GET to BrightLocal and unwrap the JSON body.

    Returns ``{"_ok": True, "data": ...}`` on success, or
    ``{"_ok": False, "error": ..., "status_code": ...}`` on failure.
    """
    params = dict(auth_params)
    if extra_params:
        for key, value in extra_params.items():
            if value is None or value == "":
                continue
            params[key] = value
    url = f"{BRIGHTLOCAL_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            text_preview = resp.text[:500] if resp.text else ""
            try:
                body = resp.json()
            except Exception:
                body = {"raw": text_preview}
            if resp.status_code != 200:
                return {
                    "_ok": False,
                    "status_code": resp.status_code,
                    "error": f"BrightLocal API error ({resp.status_code}): {text_preview}",
                }
            # BrightLocal wraps every response: { success: bool, errors: [...], response: {...} }
            if isinstance(body, dict) and body.get("success") is False:
                err = body.get("errors") or "BrightLocal returned success=false"
                return {
                    "_ok": False,
                    "status_code": 200,
                    "error": f"BrightLocal: {err}",
                }
            payload = body.get("response", body) if isinstance(body, dict) else body
            return {"_ok": True, "data": payload}
    except httpx.TimeoutException:
        return {"_ok": False, "status_code": 0, "error": "BrightLocal request timed out"}
    except Exception as exc:
        logger.exception("brightlocal request failed")
        return {"_ok": False, "status_code": 0, "error": f"BrightLocal request failed: {exc}"}


# ---------------------------------------------------------------------------
# Result normalization helpers
# ---------------------------------------------------------------------------


def _normalize_keyword_row(row: dict) -> dict:
    """Project a BrightLocal keyword row down to the fields agents care about."""
    return {
        "keyword": row.get("keyword") or row.get("name"),
        "search_engine": row.get("search_engine") or row.get("engine"),
        "location": row.get("location") or row.get("city"),
        "language": row.get("language"),
        "tracked_url": row.get("url") or row.get("tracked_url"),
        "campaign_id": row.get("campaign_id") or row.get("id"),
    }


def _normalize_ranking_row(row: dict) -> dict:
    return {
        "keyword": row.get("keyword") or row.get("name"),
        "position": row.get("rank") if row.get("rank") is not None else row.get("position"),
        "url": row.get("url") or row.get("ranking_url"),
        "search_engine": row.get("search_engine") or row.get("engine"),
        "location": row.get("location") or row.get("city"),
        "checked_at": row.get("date") or row.get("checked_at") or row.get("ranked_on"),
    }


def _flatten_results_payload(payload: Any) -> List[dict]:
    """BrightLocal LSRC results endpoints return a few different shapes
    depending on whether you're polling a single campaign or many. Flatten
    everything to a list of ranking rows."""
    rows: List[dict] = []
    if payload is None:
        return rows
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                if "results" in item and isinstance(item["results"], list):
                    rows.extend(r for r in item["results"] if isinstance(r, dict))
                else:
                    rows.append(item)
        return rows
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            rows.extend(r for r in payload["results"] if isinstance(r, dict))
        elif isinstance(payload.get("rankings"), list):
            rows.extend(r for r in payload["rankings"] if isinstance(r, dict))
        elif isinstance(payload.get("keywords"), list):
            rows.extend(r for r in payload["keywords"] if isinstance(r, dict))
        else:
            rows.append(payload)
    return rows


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def brightlocal_list_keywords(
    tenant_id: str = "",
    campaign_id: str = "",
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """List tracked keywords for the tenant's BrightLocal account.

    A vet practice with 3 Google Business Profiles typically has 3 BrightLocal
    LSRC campaigns (one per location). Without ``campaign_id`` this returns
    the keyword list across every campaign on the account.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        campaign_id: Optional BrightLocal LSRC campaign id to filter by.
        force_refresh: Skip the 4h cache and hit BrightLocal directly.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with status, count, and a normalized list of keywords.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_brightlocal_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "BrightLocal not connected. Ask the user to add their BrightLocal API key + account ID in Connected Apps (Integrations page)."
        }

    cache_key = _cache_key(tid, f"keywords:{campaign_id or 'all'}")
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])

    # If a campaign is specified, fetch keywords for that campaign; otherwise
    # list every campaign and aggregate.
    keywords: List[dict] = []
    campaign_ids: List[str] = []
    if campaign_id:
        campaign_ids = [campaign_id]
    else:
        list_resp = await _brightlocal_get(f"{BRIGHTLOCAL_LSRC_PREFIX}/get-all", auth)
        if not list_resp["_ok"]:
            return {"error": list_resp["error"]}
        rows = _flatten_results_payload(list_resp["data"])
        for row in rows:
            cid = row.get("campaign_id") or row.get("id")
            if cid:
                campaign_ids.append(str(cid))
        if not campaign_ids:
            return {
                "status": "success",
                "keywords": [],
                "count": 0,
                "campaigns": [],
                "from_cache": False,
                "note": "No BrightLocal campaigns configured on this account.",
            }

    for cid in campaign_ids:
        # Re-sign per request (signatures expire after a few minutes).
        per_auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])
        kw_resp = await _brightlocal_get(
            f"{BRIGHTLOCAL_LSRC_PREFIX}/get",
            per_auth,
            {"campaign-id": cid},
        )
        if not kw_resp["_ok"]:
            logger.warning("brightlocal: failed to list keywords for campaign %s: %s", cid, kw_resp["error"])
            continue
        for row in _flatten_results_payload(kw_resp["data"]):
            row.setdefault("campaign_id", cid)
            keywords.append(_normalize_keyword_row(row))

    result = {
        "status": "success",
        "keywords": keywords,
        "count": len(keywords),
        "campaigns": campaign_ids,
        "from_cache": False,
    }
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def brightlocal_get_rankings(
    tenant_id: str = "",
    campaign_id: str = "",
    keyword: str = "",
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Get current SERP rankings for tracked keywords.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        campaign_id: Optional campaign filter. Defaults to all campaigns.
        keyword: Optional keyword filter (case-insensitive substring match).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with status and a normalized list of {keyword, position, url, ...}.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_brightlocal_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "BrightLocal not connected. Ask the user to add their BrightLocal API key + account ID in Connected Apps."
        }

    cache_key = _cache_key(tid, f"rankings:{campaign_id or 'all'}")
    cached = None if force_refresh else _cache_get(cache_key)

    if cached is None:
        auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])
        if campaign_id:
            campaign_ids = [campaign_id]
        else:
            list_resp = await _brightlocal_get(f"{BRIGHTLOCAL_LSRC_PREFIX}/get-all", auth)
            if not list_resp["_ok"]:
                return {"error": list_resp["error"]}
            campaign_ids = [
                str(row.get("campaign_id") or row.get("id"))
                for row in _flatten_results_payload(list_resp["data"])
                if row.get("campaign_id") or row.get("id")
            ]

        rankings: List[dict] = []
        for cid in campaign_ids:
            per_auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])
            rk_resp = await _brightlocal_get(
                f"{BRIGHTLOCAL_LSRC_PREFIX}/results/get",
                per_auth,
                {"campaign-id": cid},
            )
            if not rk_resp["_ok"]:
                logger.warning("brightlocal: rankings fetch failed for campaign %s: %s", cid, rk_resp["error"])
                continue
            for row in _flatten_results_payload(rk_resp["data"]):
                row.setdefault("campaign_id", cid)
                rankings.append(_normalize_ranking_row(row))

        cached = {
            "status": "success",
            "rankings": rankings,
            "count": len(rankings),
            "campaigns": campaign_ids,
            "from_cache": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        _cache_set(cache_key, cached)
    else:
        cached = {**cached, "from_cache": True}

    if keyword:
        kw_lower = keyword.lower()
        filtered = [
            r for r in cached.get("rankings", [])
            if r.get("keyword") and kw_lower in r["keyword"].lower()
        ]
        return {**cached, "rankings": filtered, "count": len(filtered)}
    return cached


@mcp.tool()
async def brightlocal_rank_changes(
    tenant_id: str = "",
    since_days: int = 1,
    campaign_id: str = "",
    min_delta: int = 1,
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Compute rank changes vs ``since_days`` ago.

    Powers the SEO Sentinel daily run: identifies keyword positions that
    moved by more than ``min_delta`` so the SEO Optimizer agent can surface
    losses and competitor surges.

    Implementation note: BrightLocal returns historical positions inside
    each ranking row under ``rank_history`` / ``previous_rank`` (the exact
    field name varies by endpoint version). We try the most common keys
    and fall back to "no historical data" without crashing.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        since_days: Number of days back to compare (default 1 = day-over-day).
        campaign_id: Optional campaign filter.
        min_delta: Minimum absolute rank change to include (default 1 = any move).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with the diff: keyword, current_position, previous_position,
        delta (positive = improved, negative = lost ground), url.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    rankings = await brightlocal_get_rankings(
        tenant_id=tid,
        campaign_id=campaign_id,
        force_refresh=force_refresh,
        ctx=ctx,
    )
    if "error" in rankings:
        return rankings

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    changes: List[dict] = []
    for row in rankings.get("rankings", []):
        current = row.get("position")
        previous = row.get("previous_position")
        # BrightLocal sometimes returns history inline.
        if previous is None and isinstance(row.get("rank_history"), list):
            history = row["rank_history"]
            for entry in reversed(history):
                ts = entry.get("date") or entry.get("checked_at")
                if not ts:
                    continue
                try:
                    when = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when <= cutoff:
                    previous = entry.get("rank") or entry.get("position")
                    break
        if current is None or previous is None:
            continue
        try:
            current_int = int(current)
            previous_int = int(previous)
        except (TypeError, ValueError):
            continue
        # BrightLocal ranks: lower number = better position.
        # delta > 0 => moved up (improved), < 0 => dropped.
        delta = previous_int - current_int
        if abs(delta) < min_delta:
            continue
        changes.append({
            "keyword": row.get("keyword"),
            "current_position": current_int,
            "previous_position": previous_int,
            "delta": delta,
            "direction": "up" if delta > 0 else "down",
            "url": row.get("url"),
            "search_engine": row.get("search_engine"),
            "location": row.get("location"),
            "campaign_id": row.get("campaign_id"),
        })

    # Sort biggest losses first — these are what SEO Sentinel cares about.
    changes.sort(key=lambda r: r["delta"])
    losses = [c for c in changes if c["delta"] < 0]
    gains = [c for c in changes if c["delta"] > 0]

    return {
        "status": "success",
        "since_days": since_days,
        "min_delta": min_delta,
        "from_cache": rankings.get("from_cache", False),
        "summary": {
            "total_changes": len(changes),
            "losses": len(losses),
            "gains": len(gains),
            "total_keywords_compared": len(rankings.get("rankings", [])),
        },
        "changes": changes,
        "biggest_losses": losses[:10],
        "biggest_gains": list(reversed(gains))[:10],
    }


@mcp.tool()
async def brightlocal_competitor_check(
    tenant_id: str = "",
    campaign_id: str = "",
    competitor_url: str = "",
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Check competitor SERP positions on the tenant's tracked keywords.

    BrightLocal's LSRC report can include competitor URLs alongside the
    tracked business URL. This tool extracts those competitor rankings.

    May return ``{"status": "no_competitor_data"}`` if the BrightLocal plan
    tier or the LSRC campaign config doesn't include competitor tracking —
    the SEO Sentinel workflow degrades gracefully without it.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        campaign_id: Optional campaign filter.
        competitor_url: If set, return only ranks for this competitor URL.
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with status and competitor positions per keyword.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_brightlocal_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "BrightLocal not connected. Ask the user to add their BrightLocal API key + account ID in Connected Apps."
        }

    cache_key = _cache_key(tid, f"competitors:{campaign_id or 'all'}:{competitor_url or 'all'}")
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])
    if campaign_id:
        campaign_ids = [campaign_id]
    else:
        list_resp = await _brightlocal_get(f"{BRIGHTLOCAL_LSRC_PREFIX}/get-all", auth)
        if not list_resp["_ok"]:
            return {"error": list_resp["error"]}
        campaign_ids = [
            str(row.get("campaign_id") or row.get("id"))
            for row in _flatten_results_payload(list_resp["data"])
            if row.get("campaign_id") or row.get("id")
        ]

    competitor_rows: List[dict] = []
    for cid in campaign_ids:
        per_auth = _build_auth_params(extracted["api_key"], extracted["api_secret"])
        comp_resp = await _brightlocal_get(
            f"{BRIGHTLOCAL_LSRC_PREFIX}/results/get",
            per_auth,
            {"campaign-id": cid, "include": "competitors"},
        )
        if not comp_resp["_ok"]:
            # Lower API tiers reject the include=competitors flag with a 403.
            if comp_resp.get("status_code") in (402, 403):
                continue
            logger.warning("brightlocal: competitor fetch failed for campaign %s: %s", cid, comp_resp["error"])
            continue
        for row in _flatten_results_payload(comp_resp["data"]):
            competitors = row.get("competitors") or row.get("competitor_rankings") or []
            if not isinstance(competitors, list):
                continue
            for comp in competitors:
                if not isinstance(comp, dict):
                    continue
                comp_url = comp.get("url") or comp.get("ranking_url")
                if competitor_url and competitor_url.lower() not in (comp_url or "").lower():
                    continue
                competitor_rows.append({
                    "keyword": row.get("keyword") or row.get("name"),
                    "competitor_url": comp_url,
                    "position": comp.get("rank") if comp.get("rank") is not None else comp.get("position"),
                    "search_engine": row.get("search_engine") or row.get("engine"),
                    "location": row.get("location") or row.get("city"),
                    "campaign_id": cid,
                })

    if not competitor_rows:
        result = {
            "status": "no_competitor_data",
            "message": "No competitor data available — either BrightLocal plan tier doesn't include competitor tracking, or no competitors are configured in the LSRC campaign.",
            "competitors": [],
            "count": 0,
            "campaigns": campaign_ids,
            "from_cache": False,
        }
    else:
        result = {
            "status": "success",
            "competitors": competitor_rows,
            "count": len(competitor_rows),
            "campaigns": campaign_ids,
            "from_cache": False,
        }
    _cache_set(cache_key, result)
    return result
