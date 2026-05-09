"""ScribbleVet AI-scribe MCP tools.

Read-only adapter for ScribbleVet's clinical-note surface. Powers the
``ScribbleVet Note Sync`` workflow on the Animal Doctor SOC tenant (and
any other clinic tenant that connects ScribbleVet) — pulling per-visit
SOAP notes into the knowledge graph as ``clinical_note`` observations
on the patient entity. Once ingested, the Pet Health Concierge and
Clinical Triage agents can recall prior visits via ``search_knowledge``.

Tools
~~~~~
- ``scribblevet_list_recent_notes(date_range, dvm_id?)`` — list notes
  finalized in the requested window
- ``scribblevet_get_note(note_id)`` — full SOAP body
- ``scribblevet_search(query, patient_id?)`` — text search across notes

API surface — RESEARCH-GATED
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ScribbleVet does not currently publish a public API (see
``docs/research/2026-05-09-scribblevet-api-research.md``). This adapter
is scaffolded against the *probable* shape of a future
Instinct-Science-issued partner API (Instinct Science acquired
ScribbleVet 2026-01-16 and runs a Partner API on the EMR side, OAuth
client_credentials grant, REST/JSON). Endpoints are placeholders that
the partner-intake step will confirm; URLs are env-overridable so a
prod deploy can swap them once the real hostnames land.

Until partner intake completes the adapter behaves correctly in two
modes:

* **Disconnected**: returns ``{"error": "ScribbleVet not connected..."}``.
  This is what every clinic sees today.
* **Mock-API**: tests pin ``SCRIBBLEVET_BASE_URL`` to a local fixture
  server (or monkeypatch ``httpx`` directly) and exercise the entire
  pipeline (list/get/search/normalize) against the published SOAP shape.

Authentication
~~~~~~~~~~~~~~
OAuth2 client_credentials grant — same shape as the Covetrus Pulse
adapter. Credentials live in the credential vault under integration
``scribblevet`` with keys:

* ``client_id`` / ``client_secret`` — OAuth client pair issued at
  partner intake.
* ``practice_id`` — ScribbleVet practice identifier.
* ``environment`` — ``sandbox`` or ``prod`` (default ``prod``).

Caching
~~~~~~~
Note reads are cached in Redis for 4h. The 15-min ingest workflow is
the primary caller; a 4h TTL means re-runs within a workshift skip the
upstream call. ``force_refresh=True`` bypasses the cache.

If Redis is unavailable the tools degrade silently (no cache, but still
work).

Environment / sandbox
~~~~~~~~~~~~~~~~~~~~~
The base URL is selected from the credential's ``environment`` field:
``sandbox`` -> ``https://api.scribblevet.com/sandbox`` (placeholder),
``prod`` -> ``https://api.scribblevet.com``. Both URLs are overridable
via ``SCRIBBLEVET_BASE_URL_SANDBOX`` / ``SCRIBBLEVET_BASE_URL_PROD``
env vars so production deploys can swap them once Instinct/ScribbleVet
issues real partner hostnames.
"""
from __future__ import annotations

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

# Placeholder hostnames — confirmed neither at partner intake nor by
# DNS on 2026-05-09. Both are env-overridable so prod deploys swap
# without a code change.
DEFAULT_BASE_URL_PROD = "https://api.scribblevet.com"
DEFAULT_BASE_URL_SANDBOX = "https://api.scribblevet.com/sandbox"

# 4h cache TTL — same rationale as the Pulse / BrightLocal adapters:
# 15-min ingest cron + occasional ad-hoc reads.
DEFAULT_CACHE_TTL_SECONDS = 4 * 60 * 60

# OAuth token cache: refresh this many seconds before the upstream
# expiry so we don't race the cutover.
OAUTH_REFRESH_SAFETY_MARGIN_SECONDS = 60

# Resource paths under the partner API. These are placeholders against
# the SOAP shape ScribbleVet's Browser Companion writes today (see
# research doc) — confirm exact paths at partner intake.
SCRIBBLEVET_PATH_LIST_NOTES = "/v1/notes"
SCRIBBLEVET_PATH_GET_NOTE = "/v1/notes/{note_id}"
SCRIBBLEVET_PATH_SEARCH_NOTES = "/v1/notes/search"
SCRIBBLEVET_PATH_OAUTH_TOKEN = "/oauth/token"


# ---------------------------------------------------------------------------
# Helpers — config + credential vault
# ---------------------------------------------------------------------------


def _get_api_base_url() -> str:
    from src.config import settings

    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings

    return settings.API_INTERNAL_KEY


def _get_scribblevet_base_url(environment: str) -> str:
    """Pick the ScribbleVet base URL for the credential's ``environment``."""
    if (environment or "").lower() == "sandbox":
        return os.environ.get(
            "SCRIBBLEVET_BASE_URL_SANDBOX", DEFAULT_BASE_URL_SANDBOX
        ).rstrip("/")
    return os.environ.get(
        "SCRIBBLEVET_BASE_URL_PROD", DEFAULT_BASE_URL_PROD
    ).rstrip("/")


async def _get_scribblevet_credentials(tenant_id: str) -> Optional[dict]:
    """Retrieve ScribbleVet credentials from the vault for this tenant."""
    api_base_url = _get_api_base_url()
    internal_key = _get_internal_key()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{api_base_url}/api/v1/oauth/internal/token/scribblevet",
                headers={"X-Internal-Key": internal_key},
                params={"tenant_id": tenant_id},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("scribblevet credential retrieval returned %s", resp.status_code)
    except Exception:
        logger.exception("Failed to retrieve scribblevet credentials")
    return None


def _extract_credentials(creds: Optional[dict]) -> Optional[Dict[str, Any]]:
    """Pull client_id/client_secret/practice_id/environment out of vault payload.

    Accepts camelCase aliases for ergonomics. Returns None if either
    OAuth credential is missing — that becomes a "not connected" error
    in each tool.
    """
    if not creds:
        return None
    client_id = creds.get("client_id") or creds.get("clientId")
    client_secret = creds.get("client_secret") or creds.get("clientSecret")
    practice_id = creds.get("practice_id") or creds.get("practiceId")
    environment = (creds.get("environment") or "prod").lower()
    if not client_id or not client_secret:
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "practice_id": practice_id or "",
        "environment": environment,
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
        logger.info("scribblevet: redis cache enabled at %s", url)
    except Exception as exc:
        logger.info("scribblevet: redis cache unavailable (%s); running uncached", exc)
        _redis_client = None
    return _redis_client


def _cache_key(tenant_id: str, suffix: str) -> str:
    return f"scribblevet:{tenant_id}:{suffix}"


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
        logger.exception("scribblevet: cache read failed for %s", key)
        return None


def _cache_set(key: str, value: dict, ttl: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        logger.exception("scribblevet: cache write failed for %s", key)


# ---------------------------------------------------------------------------
# OAuth token cache + exchange
# ---------------------------------------------------------------------------

# Per-process cache: { (client_id, base_url) -> (token, expires_at_ts) }.
# Single-pod MCP server, so no need for cross-pod sharing via Redis.
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
    url = f"{base_url}{SCRIBBLEVET_PATH_OAUTH_TOKEN}"
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
                    "scribblevet oauth token failed (%s): %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return None
            body = resp.json()
            token = body.get("access_token")
            expires_in = int(body.get("expires_in", 3600))
            if not token:
                logger.warning("scribblevet oauth response missing access_token")
                return None
            return token, expires_in
    except Exception:
        logger.exception("scribblevet oauth token request failed")
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
# Helpers — upstream HTTP (Bearer-token flow)
# ---------------------------------------------------------------------------


async def _scribblevet_request(
    method: str,
    path: str,
    creds: Dict[str, Any],
    extra_params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Issue an authenticated request to ScribbleVet.

    Returns ``{"_ok": True, "data": ...}`` on success or
    ``{"_ok": False, "error": ..., "status_code": ...}`` on failure.

    Most tools use GET; ``scribblevet_search`` issues POST with a JSON
    body so a placeholder ``method`` is exposed.
    """
    base_url = _get_scribblevet_base_url(creds.get("environment", "prod"))
    url = f"{base_url}{path}"
    headers: Dict[str, str] = {"Accept": "application/json"}

    token = await _get_oauth_token(
        creds["client_id"], creds["client_secret"], base_url
    )
    if not token:
        return {
            "_ok": False,
            "status_code": 0,
            "error": "ScribbleVet OAuth token exchange failed (check client_id/client_secret + environment).",
        }
    headers["Authorization"] = f"Bearer {token}"

    params: Dict[str, Any] = {}
    if extra_params:
        for key, value in extra_params.items():
            if value is None or value == "":
                continue
            params[key] = value

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method.upper() == "POST":
                resp = await client.post(
                    url, params=params, headers=headers, json=json_body or {}
                )
            else:
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
                    "error": f"ScribbleVet API error ({resp.status_code}): {text_preview}",
                }
            return {"_ok": True, "data": body}
    except httpx.TimeoutException:
        return {"_ok": False, "status_code": 0, "error": "ScribbleVet request timed out"}
    except Exception as exc:
        logger.exception("scribblevet request failed")
        return {"_ok": False, "status_code": 0, "error": f"ScribbleVet request failed: {exc}"}


# ---------------------------------------------------------------------------
# Helpers — date-range parsing
# ---------------------------------------------------------------------------


def _parse_date_range(date_range: str) -> Tuple[str, str]:
    """Parse a date_range string into (start_iso, end_iso).

    Used for the 15-min ingest workflow. Accepts:

    * ``"15m"`` / ``"60m"`` — N minutes back through now (ISO-8601 with TZ)
    * ``"1d"`` / ``"7d"`` — N days back through now
    * ``"YYYY-MM-DD/YYYY-MM-DD"`` — explicit range (start-of-day → end-of-day)
    * ``"today"`` — start-of-day-today → now
    """
    now = datetime.now(timezone.utc)
    if not date_range or date_range.strip().lower() == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(), now.isoformat()
    s = date_range.strip().lower()
    if s.endswith("m") and s[:-1].isdigit():
        minutes = int(s[:-1])
        start = now - timedelta(minutes=max(minutes, 0))
        return start.isoformat(), now.isoformat()
    if s.endswith("d") and s[:-1].isdigit():
        days = int(s[:-1])
        start = now - timedelta(days=max(days, 0))
        return start.isoformat(), now.isoformat()
    if "/" in date_range:
        a, b = date_range.split("/", 1)
        return a.strip(), b.strip()
    # Fallback: pass-through (the API can interpret arbitrary strings).
    return date_range, date_range


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def _normalize_note_summary(row: Any) -> dict:
    """Project a list-endpoint note row to summary fields.

    Summary list endpoints typically return enough to drive the ingest
    workflow's idempotency check (note_id, visit_date, patient ref) plus
    a teaser. The full SOAP body is fetched separately via
    ``scribblevet_get_note``.
    """
    if not isinstance(row, dict):
        return {}
    return {
        "note_id": row.get("id") or row.get("note_id"),
        "visit_date": row.get("visit_date") or row.get("date") or row.get("created_at"),
        "finalized_at": row.get("finalized_at") or row.get("updated_at"),
        "dvm_id": row.get("dvm_id") or row.get("doctor_id"),
        "dvm_name": row.get("dvm_name") or row.get("doctor"),
        "patient_id": row.get("patient_id"),
        "patient_name": row.get("patient_name"),
        "client_id": row.get("client_id") or row.get("owner_id"),
        "client_name": row.get("client_name") or row.get("owner_name"),
        "species": row.get("species"),
        "summary": row.get("summary") or row.get("teaser"),
        "status": row.get("status"),
    }


def _normalize_note_full(row: Any) -> dict:
    """Project a full SOAP note payload to the fields agents care about.

    The SOAP shape is the lowest-common-denominator across ScribbleVet's
    documented Browser-Companion sections (subjective / objective /
    assessment / plan / client take-home / dental chart). Multi-pet
    visits are surfaced as a list so the ingest workflow can split one
    upstream note into per-pet observations.
    """
    if not isinstance(row, dict):
        return {}
    soap = row.get("soap") or {}
    return {
        "note_id": row.get("id") or row.get("note_id"),
        "visit_date": row.get("visit_date") or row.get("date"),
        "finalized_at": row.get("finalized_at") or row.get("updated_at"),
        "dvm_id": row.get("dvm_id") or row.get("doctor_id"),
        "dvm_name": row.get("dvm_name") or row.get("doctor"),
        "location_id": row.get("location_id") or row.get("location"),
        "patient_id": row.get("patient_id"),
        "patient_name": row.get("patient_name"),
        "species": row.get("species"),
        "breed": row.get("breed"),
        "sex": row.get("sex"),
        "date_of_birth": row.get("date_of_birth") or row.get("dob"),
        "weight": row.get("weight"),
        "client_id": row.get("client_id") or row.get("owner_id"),
        "client_name": row.get("client_name") or row.get("owner_name"),
        "client_phone": row.get("client_phone") or row.get("owner_phone"),
        "subjective": (soap.get("subjective") if isinstance(soap, dict) else None)
        or row.get("subjective"),
        "objective": (soap.get("objective") if isinstance(soap, dict) else None)
        or row.get("objective"),
        "assessment": (soap.get("assessment") if isinstance(soap, dict) else None)
        or row.get("assessment"),
        "plan": (soap.get("plan") if isinstance(soap, dict) else None) or row.get("plan"),
        "client_instructions": row.get("client_instructions")
        or row.get("take_home_instructions"),
        "dental_chart": row.get("dental_chart"),
        "diagnoses": row.get("diagnoses") or [],
        "medications": row.get("medications") or row.get("prescriptions") or [],
        "vaccines_administered": row.get("vaccines_administered")
        or row.get("vaccines")
        or [],
        "additional_pets": row.get("additional_pets") or [],
        "status": row.get("status"),
    }


def _flatten_list_payload(payload: Any) -> List[dict]:
    """Tolerate the several envelope shapes a list/search endpoint can return."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "notes", "items", "matches"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
        return [payload]
    return []


def _build_soap_text(note: Dict[str, Any]) -> str:
    """Render a normalized note into the canonical observation_text the
    ingest workflow stores as a ``clinical_note`` observation.

    Format is deliberately structured (S/O/A/P headers + take-home) so a
    later ``search_knowledge`` recall can show the operator a coherent
    snippet rather than a wall of free text. Empty sections are skipped.
    """
    parts: List[str] = []
    header_bits = []
    if note.get("visit_date"):
        header_bits.append(f"Visit: {note['visit_date']}")
    if note.get("dvm_name"):
        header_bits.append(f"DVM: {note['dvm_name']}")
    if note.get("location_id"):
        header_bits.append(f"Location: {note['location_id']}")
    if note.get("patient_name"):
        header_bits.append(f"Patient: {note['patient_name']}")
    if header_bits:
        parts.append(" | ".join(header_bits))

    sections = [
        ("S (Subjective)", note.get("subjective")),
        ("O (Objective)", note.get("objective")),
        ("A (Assessment)", note.get("assessment")),
        ("P (Plan)", note.get("plan")),
        ("Client instructions", note.get("client_instructions")),
    ]
    for label, body in sections:
        text = body if isinstance(body, str) else None
        if not text or not text.strip():
            continue
        parts.append(f"\n{label}:\n{text.strip()}")

    diags = note.get("diagnoses") or []
    if diags:
        diag_lines = []
        for d in diags:
            if isinstance(d, dict):
                diag_lines.append(d.get("name") or d.get("description") or json.dumps(d))
            else:
                diag_lines.append(str(d))
        parts.append("\nDiagnoses: " + "; ".join(diag_lines))

    meds = note.get("medications") or []
    if meds:
        med_lines = []
        for m in meds:
            if isinstance(m, dict):
                name = m.get("name") or m.get("drug") or "?"
                dose = m.get("dose") or m.get("instructions") or ""
                med_lines.append(f"{name} {dose}".strip())
            else:
                med_lines.append(str(m))
        parts.append("\nMedications: " + "; ".join(med_lines))

    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def scribblevet_list_recent_notes(
    tenant_id: str = "",
    date_range: str = "15m",
    dvm_id: str = "",
    location_id: str = "",
    limit: int = 200,
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """List ScribbleVet notes finalized in the requested window.

    The ``ScribbleVet Note Sync`` workflow runs every 15 minutes with
    ``date_range="15m"``; ad-hoc Luna queries pass longer ranges.

    Args:
        tenant_id: Tenant UUID (resolved from session if omitted).
        date_range: ``"15m"`` / ``"1d"`` / ``"7d"`` for relative ranges,
            or explicit ``"YYYY-MM-DD/YYYY-MM-DD"``. Default ``"15m"``.
        dvm_id: Optional. Filter to one veterinarian's notes.
        location_id: Optional. Filter to one practice location.
        limit: Max rows to return (default 200; upper-bounded at 1000).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with ``notes`` (list of normalized summaries) and ``count``.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}

    creds = await _get_scribblevet_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "ScribbleVet not connected. Ask the user to add their ScribbleVet partner credentials (client_id + client_secret + practice_id) in Connected Apps.",
        }

    capped_limit = max(1, min(int(limit or 200), 1000))
    start_iso, end_iso = _parse_date_range(date_range)

    cache_key = _cache_key(
        tid,
        f"list:{start_iso}:{end_iso}:{dvm_id or 'all'}:{location_id or 'all'}:{capped_limit}",
    )
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    extra: Dict[str, Any] = {
        "start": start_iso,
        "end": end_iso,
        "limit": capped_limit,
    }
    if extracted.get("practice_id"):
        extra["practice_id"] = extracted["practice_id"]
    if dvm_id:
        extra["dvm_id"] = dvm_id
    if location_id:
        extra["location_id"] = location_id

    resp = await _scribblevet_request(
        "GET", SCRIBBLEVET_PATH_LIST_NOTES, extracted, extra
    )
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    rows = _flatten_list_payload(resp["data"])
    normalized = [_normalize_note_summary(r) for r in rows if r]
    # Drop rows we couldn't normalize (no note_id) so the ingest workflow
    # never tries to record_observation against an empty key.
    normalized = [n for n in normalized if n.get("note_id")]

    result = {
        "status": "success",
        "notes": normalized,
        "count": len(normalized),
        "date_range": {"start": start_iso, "end": end_iso},
        "dvm_id": dvm_id or None,
        "location_id": location_id or None,
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def scribblevet_get_note(
    note_id: str = "",
    tenant_id: str = "",
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Fetch a full ScribbleVet SOAP note by ID.

    Returns the normalized SOAP body plus a pre-rendered ``soap_text``
    field that the ingest workflow stores as ``observation_text`` on a
    ``clinical_note`` observation. The same render is what
    ``search_knowledge`` will surface to Pet Health Concierge replies.

    Args:
        note_id: ScribbleVet note ID. Required.
        tenant_id: Tenant UUID (resolved from session if omitted).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with ``note`` (normalized) and ``soap_text``, or
        ``{"error": "..."}`` on failure.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}
    if not note_id:
        return {"error": "note_id is required."}

    creds = await _get_scribblevet_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "ScribbleVet not connected. Ask the user to add their ScribbleVet partner credentials in Connected Apps.",
        }

    cache_key = _cache_key(tid, f"note:{note_id}")
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    path = SCRIBBLEVET_PATH_GET_NOTE.format(note_id=note_id)
    extra: Dict[str, Any] = {}
    if extracted.get("practice_id"):
        extra["practice_id"] = extracted["practice_id"]

    resp = await _scribblevet_request("GET", path, extracted, extra)
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    note = _normalize_note_full(resp["data"])
    if not note.get("note_id"):
        return {
            "error": "ScribbleVet returned an unexpected payload — note not found.",
            "raw": resp["data"],
        }

    result = {
        "status": "success",
        "note": note,
        "soap_text": _build_soap_text(note),
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def scribblevet_search(
    query: str = "",
    tenant_id: str = "",
    patient_id: str = "",
    limit: int = 50,
    force_refresh: bool = False,
    ctx: Context = None,
) -> dict:
    """Text-search across ScribbleVet notes.

    Used by Pet Health Concierge for "have you seen Bella for limp
    before?" style lookups when the local knowledge graph misses a
    match (e.g. a recent visit not yet ingested by the 15-min cron).

    Args:
        query: Free-text search query. Required.
        tenant_id: Tenant UUID (resolved from session if omitted).
        patient_id: Optional. Restrict search to a single patient.
        limit: Max matches (default 50; upper-bounded at 200).
        force_refresh: Skip the 4h cache.
        ctx: MCP request context (injected automatically).

    Returns:
        Dict with ``matches`` (list of summary rows) and ``count``.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not tid:
        return {"error": "tenant_id is required."}
    if not query:
        return {"error": "query is required."}

    creds = await _get_scribblevet_credentials(tid)
    extracted = _extract_credentials(creds) if creds else None
    if not extracted:
        return {
            "error": "ScribbleVet not connected. Ask the user to add their ScribbleVet partner credentials in Connected Apps.",
        }

    capped_limit = max(1, min(int(limit or 50), 200))
    cache_key = _cache_key(
        tid, f"search:{query}:{patient_id or 'any'}:{capped_limit}"
    )
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    body: Dict[str, Any] = {"query": query, "limit": capped_limit}
    if patient_id:
        body["patient_id"] = patient_id
    if extracted.get("practice_id"):
        body["practice_id"] = extracted["practice_id"]

    resp = await _scribblevet_request(
        "POST", SCRIBBLEVET_PATH_SEARCH_NOTES, extracted, json_body=body
    )
    if not resp["_ok"]:
        return {"error": resp["error"], "status_code": resp.get("status_code", 0)}

    rows = _flatten_list_payload(resp["data"])
    normalized = [_normalize_note_summary(r) for r in rows if r]
    normalized = [n for n in normalized if n.get("note_id")]

    result = {
        "status": "success",
        "matches": normalized,
        "count": len(normalized),
        "query": query,
        "patient_id": patient_id or None,
        "from_cache": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, result)
    return result
