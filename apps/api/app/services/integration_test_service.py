"""Live credential testing for tenant-scoped integrations.

Each integration that supports a "Test" button registers a low-cost upstream
call here. Today: ``brightlocal``. The pattern is intentionally minimal so
adding a new integration is a single function + dispatch entry.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any, Awaitable, Callable, Dict

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BrightLocal — uses the cheapest LSRC list endpoint to confirm signing works.
# ---------------------------------------------------------------------------

BRIGHTLOCAL_BASE_URL = "https://tools.brightlocal.com/seo-tools/api"


def _brightlocal_sign(api_key: str, api_secret: str, expires_ts: int) -> str:
    payload = f"{api_key}{expires_ts}".encode("utf-8")
    digest = hmac.new(api_secret.encode("utf-8"), payload, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


async def _test_brightlocal(creds: Dict[str, Any]) -> Dict[str, Any]:
    api_key = creds.get("api_key") or creds.get("apiKey")
    api_secret = creds.get("api_secret") or creds.get("apiSecret") or creds.get("secret") or api_key
    if not api_key:
        return {"ok": False, "error": "Missing API Key. Add it in the credential form and try again."}

    expires_ts = int(time.time()) + 300
    params = {
        "api-key": api_key,
        "expires": str(expires_ts),
        "sig": _brightlocal_sign(api_key, api_secret, expires_ts),
    }
    url = f"{BRIGHTLOCAL_BASE_URL}/v2/lsrc/get-all"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            text_preview = (resp.text or "")[:300]
            try:
                body = resp.json()
            except Exception:
                body = {"raw": text_preview}

            if resp.status_code == 200 and (
                not isinstance(body, dict) or body.get("success") is not False
            ):
                # Try to count campaigns so the user gets meaningful confirmation.
                payload = body.get("response") if isinstance(body, dict) else None
                campaign_count = None
                if isinstance(payload, list):
                    campaign_count = len(payload)
                elif isinstance(payload, dict):
                    if isinstance(payload.get("results"), list):
                        campaign_count = len(payload["results"])
                return {
                    "ok": True,
                    "integration": "brightlocal",
                    "message": (
                        f"Authenticated successfully. {campaign_count} campaign(s) on this account."
                        if campaign_count is not None
                        else "Authenticated successfully."
                    ),
                }
            errors = body.get("errors") if isinstance(body, dict) else None
            return {
                "ok": False,
                "integration": "brightlocal",
                "status_code": resp.status_code,
                "error": (
                    f"BrightLocal rejected the credentials: {errors or text_preview or resp.status_code}"
                ),
            }
    except httpx.TimeoutException:
        return {"ok": False, "integration": "brightlocal", "error": "BrightLocal request timed out"}
    except Exception as exc:
        logger.exception("brightlocal credential test failed")
        return {"ok": False, "integration": "brightlocal", "error": f"BrightLocal request failed: {exc}"}


# ---------------------------------------------------------------------------
# ScribbleVet — exchanges OAuth2 client_credentials so the operator
# learns immediately whether their partner-issued client_id/secret pair
# is valid. Until ScribbleVet/Instinct's partner program issues real
# credentials this will fail with a friendly "ScribbleVet rejected the
# credentials" message — that's the expected state for any tenant who
# hasn't completed partner intake yet.
# ---------------------------------------------------------------------------

import os as _os

DEFAULT_SCRIBBLEVET_BASE_URL_PROD = "https://api.scribblevet.com"
DEFAULT_SCRIBBLEVET_BASE_URL_SANDBOX = "https://api.scribblevet.com/sandbox"


def _scribblevet_base_url(environment: str) -> str:
    if (environment or "").lower() == "sandbox":
        return _os.environ.get(
            "SCRIBBLEVET_BASE_URL_SANDBOX", DEFAULT_SCRIBBLEVET_BASE_URL_SANDBOX
        ).rstrip("/")
    return _os.environ.get(
        "SCRIBBLEVET_BASE_URL_PROD", DEFAULT_SCRIBBLEVET_BASE_URL_PROD
    ).rstrip("/")


async def _test_scribblevet(creds: Dict[str, Any]) -> Dict[str, Any]:
    client_id = creds.get("client_id") or creds.get("clientId")
    client_secret = creds.get("client_secret") or creds.get("clientSecret")
    environment = (creds.get("environment") or "prod").lower()

    if not client_id or not client_secret:
        return {
            "ok": False,
            "integration": "scribblevet",
            "error": "Missing Client ID or Client Secret. Add both in the credential form and try again.",
        }

    base_url = _scribblevet_base_url(environment)
    url = f"{base_url}/oauth/token"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            text_preview = (resp.text or "")[:300]
            try:
                body = resp.json()
            except Exception:
                body = {"raw": text_preview}

            if resp.status_code == 200 and isinstance(body, dict) and body.get("access_token"):
                return {
                    "ok": True,
                    "integration": "scribblevet",
                    "message": f"Authenticated successfully against ScribbleVet ({environment}).",
                }
            err = (
                body.get("error_description")
                or body.get("error")
                if isinstance(body, dict)
                else None
            )
            return {
                "ok": False,
                "integration": "scribblevet",
                "status_code": resp.status_code,
                "error": (
                    f"ScribbleVet rejected the credentials: {err or text_preview or resp.status_code}. "
                    "If you haven't completed partner intake yet, this is expected — see "
                    "docs/research/2026-05-09-scribblevet-api-research.md for the access path."
                ),
            }
    except httpx.TimeoutException:
        return {"ok": False, "integration": "scribblevet", "error": "ScribbleVet request timed out"}
    except Exception as exc:
        logger.exception("scribblevet credential test failed")
        return {"ok": False, "integration": "scribblevet", "error": f"ScribbleVet request failed: {exc}"}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_TESTERS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "brightlocal": _test_brightlocal,
    "scribblevet": _test_scribblevet,
}


async def test_integration(integration_name: str, creds: Dict[str, Any]) -> Dict[str, Any]:
    tester = _TESTERS.get(integration_name)
    if tester is None:
        return {
            "ok": False,
            "integration": integration_name,
            "error": f"Test not supported for '{integration_name}' yet.",
        }
    return await tester(creds)
