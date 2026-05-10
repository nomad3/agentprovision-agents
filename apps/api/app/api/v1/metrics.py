"""Prometheus ``/api/v1/metrics`` exposition endpoint — Phase 3 commit 4.

Mounts a single ``GET /api/v1/metrics`` route that calls
``prometheus_client.generate_latest()`` against the default registry
and returns the OpenMetrics-text body. Auth: ``X-Internal-Key`` header
(matches the RL internal endpoint pattern in
``apps/api/app/api/v1/rl.py:23-27``).

The 4 Phase 2 metrics + the new Phase 3 preflight histogram are all
on the default registry, so the same scraper can pull them all.

Internal-key auth (not public) — Prometheus inside the cluster runs
with the key in its scrape config. Public scraping is blocked by the
Cloudflare-tunnel rule at the edge (``/api/v1/*/internal/*`` is the
documented internal pattern; we extend that to ``/metrics`` since the
intent matches: in-cluster scrapes, never public).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response

from app.core.config import settings

router = APIRouter()


def _verify_internal_key(
    x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key"),
):
    if x_internal_key not in (settings.API_INTERNAL_KEY, settings.MCP_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid internal key")


@router.get("/metrics")
def metrics(_auth: None = Depends(_verify_internal_key)) -> Response:
    """Return Prometheus exposition-format metrics from the default registry."""
    try:
        from prometheus_client import (
            CONTENT_TYPE_LATEST,
            generate_latest,
            REGISTRY,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail=f"prometheus_client not installed: {exc}",
        )
    body = generate_latest(REGISTRY)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)


__all__ = ["router"]
