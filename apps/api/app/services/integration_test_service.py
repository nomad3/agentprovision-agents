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
# Dispatch
# ---------------------------------------------------------------------------

_TESTERS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "brightlocal": _test_brightlocal,
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
