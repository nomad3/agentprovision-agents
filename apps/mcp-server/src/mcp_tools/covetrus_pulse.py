"""Covetrus Pulse Connect MCP tools.

Read-only adapter for the Covetrus Connect Technology Integration Partner
Program. Powers three Animal-Doctor-SOC (and future VMG-tenant) workflows:

* Pet Health Concierge (Herriot replacement) — record-aware client replies
* Multi-Site Revenue Sync — daily per-location revenue rollups
* Bookkeeper cross-reference — invoice + line-item read for accounting

API surface
~~~~~~~~~~~
- ``pulse_get_patient`` — patient signalment, vaccines, current Rx, allergies,
  weight history, diagnoses, last-visit summary
- ``pulse_list_appointments`` — schedule + completed visits in a date range,
  filtered by location
- ``pulse_query_invoices`` — billing line items in a date range, filtered by
  location

Authentication — DUAL FLOW SCAFFOLD
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The 2026-05-09 research confirmed Covetrus Connect uses an OAuth-style
``client_id`` + ``client_secret`` credential pair, but the exact wire
format (OAuth2 client_credentials grant vs HMAC-signed query strings)
is not publicly documented. We scaffold BOTH flows behind the
``PULSE_AUTH_FLOW`` env var (default ``oauth``, override ``hmac``) so the
moment partner intake confirms which flow the API actually uses, the
adapter lights up without further engineering.

* OAuth2 client_credentials (default): POST to /oauth/token with
  ``grant_type=client_credentials``, cache the access_token until just
  before expiry, then ``Authorization: Bearer <token>`` on every call.
* HMAC (BrightLocal-style fallback): every request signed with
  ``base64(HMAC-SHA256(client_id + expires + path, client_secret))`` and
  three params ``api-key``, ``sig``, ``expires`` appended to the query
  string.

Either way, credentials live in the credential vault under integration
``covetrus_pulse`` with keys ``client_id``, ``client_secret``,
``practice_id``, and ``environment`` (sandbox|prod).

Caching
~~~~~~~
Patient + appointment + invoice reads are cached in Redis for 4h (same
pattern as BrightLocal). The Multi-Site Revenue Sync workflow runs once
per day, so a 4h TTL guarantees one upstream call per (tenant, query)
per day plus headroom for ad-hoc Luna queries within a workshift.
``force_refresh=True`` bypasses the cache.

If Redis is unavailable the tools degrade silently (no cache, but still
work).

Environment / sandbox
~~~~~~~~~~~~~~~~~~~~~
The base URL is selected from the credential's ``environment`` field:
``sandbox`` -> ``https://api.covetrus.com/sandbox`` (placeholder; confirm
at partner intake), ``prod`` -> ``https://api.covetrus.com``. Both URLs
are overridable via ``PULSE_BASE_URL_SANDBOX`` / ``PULSE_BASE_URL_PROD``
env vars so production deploys can swap them once Covetrus issues real
sandbox / prod hostnames.
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
from typing import Any, Dict, List, Optional, Tuple

import httpx
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Covetrus NA API root (verified live host: https://api.covetrus.com/, label
# ``Covetrus NA API``, environment ``ex-prod01``). Sandbox URL is gated and
# will be confirmed at partner intake — env-var override means prod deploys
# don't need a code change to pick up the real URL.
DEFAULT_BASE_URL_PROD = "https://api.covetrus.com"
DEFAULT_BASE_URL_SANDBOX = "https://api.covetrus.com/sandbox"

# 4h cache TTL — same rationale as the BrightLocal adapter: per-day
# workflows + occasional ad-hoc reads.
DEFAULT_CACHE_TTL_SECONDS = 4 * 60 * 60

# OAuth token cache: the token TTL minus this safety margin so we refresh
# before the upstream rejects the cached token.
OAUTH_REFRESH_SAFETY_MARGIN_SECONDS = 60

# HMAC signing window — keep tight enough that signatures don't survive
# token-replay long after the call. BrightLocal uses 300s; same here.
HMAC_SIG_WINDOW_SECONDS = 300

# Resource paths under the partner API. These are placeholders against the
# Otto / SmartFlow / Chckvet partner-published scopes — confirm exact paths
# at partner intake.
PULSE_PATH_PATIENT = "/v1/patients/{patient_id}"
PULSE_PATH_APPOINTMENTS = "/v1/appointments"
PULSE_PATH_INVOICES = "/v1/invoices"
PULSE_PATH_OAUTH_TOKEN = "/oauth/token"


# ---------------------------------------------------------------------------
# Helpers — config + credential vault
# ---------------------------------------------------------------------------


def _get_api_base_url() -> str:
    from src.config import settings

    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings

    return settings.API_INTERNAL_KEY


def _get_pulse_base_url(environment: str) -> str:
    """Pick the Pulse base URL for the credential's ``environment`` field.

    Both URLs are env-overridable so prod deploys can swap them once
    Covetrus issues real hostnames.
    """
    if (environment or "").lower() == "sandbox":
        return os.environ.get("PULSE_BASE_URL_SANDBOX", DEFAULT_BASE_URL_SANDBOX).rstrip("/")
    return os.environ.get("PULSE_BASE_URL_PROD", DEFAULT_BASE_URL_PROD).rstrip("/")


def _get_auth_flow() -> str:
    """Return the active auth flow — ``oauth`` (default) or ``hmac``."""
    flow = (os.environ.get("PULSE_AUTH_FLOW") or "oauth").lower()
    if flow not in ("oauth", "hmac"):
        logger.warning("PULSE_AUTH_FLOW=%s unrecognized — falling back to oauth", flow)
        return "oauth"
    return flow


async def _get_pulse_credentials(tenant_id: str) -> Optional[dict]:
    """Retrieve Covetrus Pulse credentials from the vault for this tenant."""
    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v1/oauth/internal/token/covetrus_pulse",
                headers={"X-Internal-Key": internal_key},
                params={"tenant_id": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("covetrus_pulse credential retrieval returned %s", resp.status_code)
    except Exception:
        logger.exception("Failed to retrieve covetrus_pulse credentials")
    return None


def _extract_credentials(creds: Optional[dict]) -> Optional[Dict[str, Any]]:
    """Pull client_id/client_secret/practice_id/environment/location_ids out of a vault payload.

    Accepts camelCase aliases for ergonomics. ``location_ids`` is optional
    and may be a comma-separated string OR a list.
    """
    if not creds:
        return None
    client_id = creds.get("client_id") or creds.get("clientId")
    client_secret = creds.get("client_secret") or creds.get("clientSecret")
    practice_id = creds.get("practice_id") or creds.get("practiceId")
    environment = (creds.get("environment") or "prod").lower()
    raw_locations = creds.get("location_ids") or creds.get("locationIds") or ""
    if isinstance(raw_locations, str):
        location_ids = [x.strip() for x in raw_locations.split(",") if x.strip()]
    elif isinstance(raw_locations, list):
        location_ids = [str(x).strip() for x in raw_locations if str(x).strip()]
    else:
        location_ids = []
    if not client_id or not client_secret:
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "practice_id": practice_id or "",
        "environment": environment,
        "location_ids": location_ids,
    }


# ---------------------------------------------------------------------------
# Helpers — Redis cache (degrades to no-op on failure)
# ---------------------------------------------------------------------------


_redis_client = None
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
        _redis_client.ping()
        logger.info("covetrus_pulse: redis cache enabled at %s", url)
    except Exception as exc:
        logger.info("covetrus_pulse: redis cache unavailable (%s); running uncached", exc)
        _redis_client = None
    return _redis_client


def _cache_key(tenant_id: str, suffix: str) -> str:
    return f"covetrus_pulse:{tenant_id}:{suffix}"


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
        logger.exception("covetrus_pulse: cache read failed for %s", key)
        return None


def _cache_set(key: str, value: dict, ttl: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        logger.exception("covetrus_pulse: cache write failed for %s", key)


# ---------------------------------------------------------------------------
# Auth flow — OAuth2 client_credentials branch
# ---------------------------------------------------------------------------


# In-process OAuth token cache: { (client_id, base_url) -> (token, expires_at_ts) }
# Per-process is fine because the MCP server is a single pod; persistent
# token sharing across pods would go through Redis but we don't need it
# for the partner-API call volumes we'll see.
_oauth_token_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


async def _fetch_oauth_token(
    client_id: str,
    client_secret: str,
    base_url: str,
) -> Optional[Tuple[str, int]]:
    """Exchange client credentials for a bearer token.

    Returns ``(access_token, expires_in_seconds)`` on success, or None on
    failure. Logs upstream errors verbosely so partner-intake debugging is
    fast.
    """
    url = f"{base_url}{PULSE_PATH_OAUTH_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "covetrus_pulse oauth token failed (%s): %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return None
            body = resp.json()
            token = body.get("access_token")
            expires_in = int(body.get("expires_in", 3600))
            if not token:
                logger.warning("covetrus_pulse oauth response missing access_token")
                return None
            return token, expires_in
    except Exception:
        logger.exception("covetrus_pulse oauth token request failed")
        return None


async def _get_oauth_token(
    client_id: str,
    client_secret: str,
    base_url: str,
) -> Optional[str]:
    """Return a cached or freshly-fetched OAuth access token."""
    cache_key = (client_id, base_url)
    cached = _oauth_token_cache.get(cache_key)
    now = time.time()
    if cached and cached[1] - OAUTH_REFRESH_SAFETY_MARGIN_SECONDS > now:
        return cached[0]
    fetched = await _fetch_oauth_token(client_id, client_secret, base_url)
    if not fetched:
        return None
    token, expires_in = fetched
    _oauth_token_cache[cache_key] = (token, now + expires_in)
    return token


# ---------------------------------------------------------------------------
# Auth flow — HMAC branch (BrightLocal-style fallback)
# ---------------------------------------------------------------------------


def _sign_hmac(client_id: str, client_secret: str, expires_ts: int, path: str) -> str:
    """HMAC-SHA256 signature over (client_id + expires + path).

    Path is included so a captured signature for one resource can't be
    replayed against another. Pattern is BrightLocal's HMAC-SHA1 helper
    upgraded to SHA-256.
    """
    payload = f"{client_id}{expires_ts}{path}".encode("utf-8")
    digest = hmac.new(client_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_hmac_params(client_id: str, client_secret: str, path: str) -> Dict[str, str]:
    expires_ts = int(time.time()) + HMAC_SIG_WINDOW_SECONDS
    return {
        "api-key": client_id,
        "sig": _sign_hmac(client_id, client_secret, expires_ts, path),
        "expires": str(expires_ts),
    }


# ---------------------------------------------------------------------------
# Helpers — upstream HTTP (auth-flow-aware)
# ---------------------------------------------------------------------------


async def _pulse_get(
    path: str,
    creds: Dict[str, Any],
    extra_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Issue a GET to Pulse via whichever auth flow is active.

    Returns ``{"_ok": True, "data": ...}`` on success or
    ``{"_ok": False, "error": ..., "status_code": ...}`` on failure.
    """
    base_url = _get_pulse_base_url(creds.get("environment", "prod"))
    flow = _get_auth_flow()
    url = f"{base_url}{path}"
    params: Dict[str, Any] = {}
    headers: Dict[str, str] = {"Accept": "application/json"}

    if flow == "oauth":
        token = await _get_oauth_token(
            creds["client_id"], creds["client_secret"], base_url
        )
        if not token:
            return {
                "_ok": False,
                "status_code": 0,
                "error": "Pulse OAuth token exchange failed (check client_id/client_secret + environment).",
            }
        headers["Authorization"] = f"Bearer {token}"
    else:  # hmac
        params.update(
            _build_hmac_params(creds["client_id"], creds["client_secret"], path)
        )

    if extra_params:
        for key, value in extra_params.items():
            if value is None or value == "":
                continue
            params[key] = value

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            text_preview = resp.text[:500] if resp.text else ""
            try:
                body = resp.json()
            except Exception:
                body = {"raw": text_preview}
            if resp.status_code != 200:
                return {
                    "_ok": False,
                    "status_code": resp.status_code,
                    "error": f"Pulse API error ({resp.status_code}): {text_preview}",
                }
            return {"_ok": True, "data": body}
    except httpx.TimeoutException:
        return {"_ok": False, "status_code": 0, "error": "Pulse request timed out"}
    except Exception as exc:
        logger.exception("covetrus_pulse request failed")
        return {"_ok": False, "status_code": 0, "error": f"Pulse request failed: {exc}"}


# ---------------------------------------------------------------------------
# Helpers — date-range parsing
# ---------------------------------------------------------------------------


def _parse_date_range(date_range: str) -> Tuple[str, str]:
    """Parse a date_range string into (start_date, end_date) ISO YYYY-MM-DD.

    Accepts:
    - ``"1d"`` / ``"7d"`` / ``"30d"`` — N days back through today (UTC)
    - ``"YYYY-MM-DD/YYYY-MM-DD"`` — explicit range
    - ``"today"`` — single-day range
    """
    today = datetime.now(timezone.utc).date()
    if not date_range or date_range.strip().lower() == "today":
        return today.isoformat(), today.isoformat()
    s = date_range.strip().lower()
    if s.endswith("d") and s[:-1].isdigit():
        days = int(s[:-1])
        start = today - timedelta(days=max(days - 1, 0))
        return start.isoformat(), today.isoformat()
    if "/" in date_range:
        a, b = date_range.split("/", 1)
        return a.strip(), b.strip()
    # Fallback: treat as single day
    return date_range, date_range


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def _normalize_patient(row: Any) -> dict:
    """Project a Pulse patient payload into the fields agents care about."""
    if not isinstance(row, dict):
        return {}
    return {
        "patient_id": row.get("id") or row.get("patient_id"),
        "name": row.get("name"),
        "species": row.get("species"),
        "breed": row.get("breed"),
        "sex": row.get("sex"),
        "date_of_birth": row.get("date_of_birth") or row.get("dob"),
        "weight_history": row.get("weight_history") or row.get("weights") or [],
        "vaccines": row.get("vaccines") or [],
        "current_medications": row.get("current_medications")
        or row.get("medications")
        or [],
        "allergies": row.get("allergies") or [],
        "diagnoses": row.get("diagnoses") or [],
        "last_visit": row.get("last_visit") or row.get("last_visit_summary"),
        "owner": row.get("owner") or row.get("client") or {},
        "location_id": row.get("location_id") or row.get("location"),
    }


def _normalize_appointment(row: Any) -> dict:
    if not isinstance(row, dict):
        return {}
    return {
        "appointment_id": row.get("id") or row.get("appointment_id"),
        "scheduled_at": row.get("scheduled_at") or row.get("start_time") or row.get("date"),
        "duration_minutes": row.get("duration_minutes") or row.get("duration"),
        "status": row.get("status"),
        "reason": row.get("reason") or row.get("type"),
        "patient_id": row.get("patient_id"),
        "patient_name": row.get("patient_name"),
        "client_name": row.get("client_name") or row.get("owner_name"),
        "doctor": row.get("doctor") or row.get("dvm"),
        "location_id": row.get("location_id") or row.get("location"),
    }


def _normalize_invoice(row: Any) -> dict:
    if not isinstance(row, dict):
        return {}
    return {
        "invoice_id": row.get("id") or row.get("invoice_id"),
        "date": row.get("date") or row.get("invoice_date"),
        "patient_id": row.get("patient_id"),
        "patient_name": row.get("patient_name"),
        "client_name": row.get("client_name") or row.get("owner_name"),
        "location_id": row.get("location_id") or row.get("location"),
        "amount": row.get("amount") or row.get("total"),
        "service_type": row.get("service_type"),
        "line_items": row.get("line_items") or row.get("lines") or [],
        "payment_status": row.get("payment_status") or row.get("status"),
    }


def _flatten_list_payload(payload: Any) -> List[dict]:
    """Pulse list endpoints can return a bare list, ``{results: [...]}``,
    ``{data: [...]}``, or ``{appointments: [...]}`` style envelopes. Flatten
    everything to a list of rows."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "appointments", "invoices", "items"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        # Single-row payload
        return [payload]
    return []


def _filter_by_locations(
    rows: List[dict],
    requested_location_id: str,
    allowed_location_ids: List[str],
) -> List[dict]:
    """Apply location_id filtering — both the per-call ``location_id`` arg
    and the credential's ``location_ids`` allowlist.

    If both are empty, no filter is applied.
    """
    if requested_location_id:
        allowed = {requested_location_id}
    elif allowed_location_ids:
        allowed = set(allowed_location_ids)
    else:
        return rows
    return [r for r in rows if r.get("location_id") in allowed]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def pulse_get_patient(
    patient_id: str = "",
    tenant_id: str = "",
    location_id: str = "",
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Fetch a patient's chart from Covetrus Pulse.

    Returns vaccines, current medications, allergies, weight history,
    diagnoses, last-visit summary, and owner contact. Used by the Pet
    Health Concierge to ground client-facing replies in the actual
    medical record.

    Args:
        patient_id: Pulse patient UUID. Required.
        tenant_id: Tenant UUID (resolved from session if omitted).
        location_id: Optional. If set, the result is sanity-checked against
            the credential's location allowlist (returns an error if the
            patient belongs to a different practice location).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with normalized patient fields, or ``{"error": "..."}``.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}
    if not patient_id:
        return {"error": "patient_id is required."}

    creds = await _get_pulse_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "Covetrus Pulse not connected. Ask the user to add their Covetrus Connect partner credentials (client_id + client_secret + practice_id) in Connected Apps."
        }

    cache_key = _cache_key(tid, f"patient:{patient_id}")
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    path = PULSE_PATH_PATIENT.format(patient_id=patient_id)
    extra: Dict[str, Any] = {}
    if extracted.get("practice_id"):
        extra["practice_id"] = extracted["practice_id"]

    resp = await _pulse_get(path, extracted, extra)
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    patient = _normalize_patient(resp["data"])
    if not patient.get("patient_id"):
        # Pulse returned 200 with a non-patient-shaped body
        return {"error": "Pulse returned an unexpected payload — patient not found.", "raw": resp["data"]}

    # Location sanity-check
    allowed = set(extracted.get("location_ids") or [])
    if location_id and patient.get("location_id") and patient["location_id"] != location_id:
        return {
            "error": f"Patient belongs to location {patient['location_id']!r}; caller asked for {location_id!r}.",
        }
    if allowed and patient.get("location_id") and patient["location_id"] not in allowed:
        return {
            "error": f"Patient belongs to location {patient['location_id']!r}, which is not in the tenant's configured location allowlist.",
        }

    result = {
        "status": "success",
        "patient": patient,
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def pulse_list_appointments(
    tenant_id: str = "",
    date_range: str = "1d",
    location_id: str = "",
    limit: int = 200,
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """List appointments + completed visits for a date range and location.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        date_range: ``"1d"``/``"7d"``/``"30d"`` for relative ranges, or
            explicit ``"YYYY-MM-DD/YYYY-MM-DD"``. Defaults to ``"1d"`` (yesterday-today).
        location_id: Optional. Filters to one location. If empty AND the
            tenant has ``location_ids`` configured in the credential, the
            result is filtered to those locations.
        limit: Max rows to return (default 200; upper-bounded at 1000).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with ``appointments`` (list) and ``count``.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_pulse_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "Covetrus Pulse not connected. Ask the user to add their Covetrus Connect partner credentials in Connected Apps."
        }

    capped_limit = max(1, min(int(limit or 200), 1000))
    start_date, end_date = _parse_date_range(date_range)

    cache_key = _cache_key(
        tid, f"appointments:{start_date}:{end_date}:{location_id or 'all'}:{capped_limit}"
    )
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    extra: Dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "limit": capped_limit,
    }
    if extracted.get("practice_id"):
        extra["practice_id"] = extracted["practice_id"]
    if location_id:
        extra["location_id"] = location_id

    resp = await _pulse_get(PULSE_PATH_APPOINTMENTS, extracted, extra)
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    rows = _flatten_list_payload(resp["data"])
    normalized = [_normalize_appointment(r) for r in rows]
    filtered = _filter_by_locations(
        normalized, location_id, extracted.get("location_ids") or []
    )

    result = {
        "status": "success",
        "appointments": filtered,
        "count": len(filtered),
        "date_range": {"start": start_date, "end": end_date},
        "location_id": location_id or None,
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def pulse_query_invoices(
    tenant_id: str = "",
    date_range: str = "1d",
    location_id: str = "",
    limit: int = 500,
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Query invoices + line items for a date range and location.

    Powers the Multi-Site Revenue Sync workflow's daily rollup. Returns
    per-invoice totals AND the raw line items so the consolidator step can
    bucket revenue by service type.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        date_range: ``"1d"``/``"7d"``/``"30d"`` or ``"YYYY-MM-DD/YYYY-MM-DD"``.
            Defaults to ``"1d"``.
        location_id: Optional. Filters to one location.
        limit: Max invoices to return (default 500; upper-bounded at 5000).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with ``invoices`` (list of normalized rows), ``count``, and a
        ``totals_by_location`` rollup so downstream agents don't need to
        reduce the list themselves.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_pulse_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "Covetrus Pulse not connected. Ask the user to add their Covetrus Connect partner credentials in Connected Apps."
        }

    capped_limit = max(1, min(int(limit or 500), 5000))
    start_date, end_date = _parse_date_range(date_range)

    cache_key = _cache_key(
        tid, f"invoices:{start_date}:{end_date}:{location_id or 'all'}:{capped_limit}"
    )
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    extra: Dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "limit": capped_limit,
    }
    if extracted.get("practice_id"):
        extra["practice_id"] = extracted["practice_id"]
    if location_id:
        extra["location_id"] = location_id

    resp = await _pulse_get(PULSE_PATH_INVOICES, extracted, extra)
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    rows = _flatten_list_payload(resp["data"])
    normalized = [_normalize_invoice(r) for r in rows]
    filtered = _filter_by_locations(
        normalized, location_id, extracted.get("location_ids") or []
    )

    # Pre-compute the per-location rollup the Multi-Site Revenue Sync
    # workflow needs. Saves the consolidator step a reduce.
    totals_by_location: Dict[str, Dict[str, Any]] = {}
    for inv in filtered:
        loc = inv.get("location_id") or "unknown"
        bucket = totals_by_location.setdefault(
            loc, {"location_id": loc, "revenue": 0.0, "invoice_count": 0, "by_service_type": {}}
        )
        amount = float(inv.get("amount") or 0)
        bucket["revenue"] += amount
        bucket["invoice_count"] += 1
        svc = inv.get("service_type") or "other"
        bucket["by_service_type"][svc] = bucket["by_service_type"].get(svc, 0.0) + amount

    result = {
        "status": "success",
        "invoices": filtered,
        "count": len(filtered),
        "totals_by_location": list(totals_by_location.values()),
        "date_range": {"start": start_date, "end": end_date},
        "location_id": location_id or None,
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result
