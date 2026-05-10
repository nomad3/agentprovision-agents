"""Shared embedding helper for mcp-server tools.

Why this module exists: ``apps/mcp-server`` previously embedded text
in process via ``sentence-transformers`` (pulls torch ~1.5GB). Two
modules (``mcp_tools/email.py`` and ``mcp_tools/knowledge.py``) carried
byte-identical local helpers. This module replaces both by calling the
API's internal embedding endpoint, which already routes to the Rust
gRPC ``embedding-service`` (with a sentence-transformers fallback in
the API pod). That keeps a single source of truth and lets us drop
the heavy ML dependency from the MCP server entirely.

Contract preserved from the previous in-process helper:

  - signature ``async def get_embedding(text, task_type='document') -> Optional[list]``
  - ``task_type`` accepts ``"document"`` or ``"query"``
  - returns ``None`` on any failure (network, auth, downstream) so
    callers can keep their best-effort indexing semantics.

Timeout: 5 seconds. The API's gRPC path also uses a 5-second timeout
internally, so 5s is enough for the fast path; the Python fallback in
the API pod warming a model on first call may be slower, but a stalled
worker is worse than a missing embedding — we'd rather skip indexing
than hold up the user-facing tool call.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Match the timeout the API uses for its own gRPC fast path. Failure
# to embed is non-fatal in every caller — better to skip indexing than
# stall a tool call.
_EMBED_TIMEOUT_SECONDS = 5.0


def _get_api_base_url() -> str:
    from src.config import settings
    return settings.API_BASE_URL.rstrip("/")


def _get_internal_key() -> str:
    from src.config import settings
    return settings.API_INTERNAL_KEY


async def get_embedding(
    text: str, task_type: str = "document"
) -> Optional[list]:
    """Generate a 768-dim embedding via the API's /internal/embed route.

    Args:
        text: Free-text to embed. Truncation is the API's job; we
            ship the raw string up to a sane upper bound so the wire
            isn't the bottleneck.
        task_type: ``"document"`` (default, search_document prefix on
            the API side) or ``"query"`` (search_query prefix).

    Returns:
        768-dim list of floats on success, or ``None`` if the call
        timed out, the API returned an error, or the API itself
        returned a null embedding (graceful failure of both gRPC and
        Python fallback paths upstream).
    """
    if not text:
        return None

    # Match the previous in-process truncation so we don't change the
    # wire payload size envelope.
    payload = {"text": text[:8000], "task_type": task_type}
    url = f"{_get_api_base_url()}/api/v1/internal/embed"
    headers = {"X-Internal-Key": _get_internal_key()}

    try:
        async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as exc:  # network, timeout, DNS, etc.
        logger.warning("Embedding call failed (%s): %s", type(exc).__name__, exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "Embedding call returned HTTP %s: %s",
            resp.status_code,
            resp.text[:200],
        )
        return None

    try:
        data = resp.json()
    except Exception as exc:
        logger.warning("Embedding response not JSON: %s", exc)
        return None

    embedding = data.get("embedding")
    if embedding is None:
        # API surfaced a graceful null — both upstream paths failed.
        return None
    return embedding
