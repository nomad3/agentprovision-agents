"""Web research MCP tools.

Three tools shipped here:

  * ``web_search`` — query the web for general information. Uses Tavily
    when a tenant has the credential configured (best quality);
    otherwise falls back to a DuckDuckGo HTML scrape (no API key
    required, lower quality, rate-limited).
  * ``fetch_url`` — fetch a single URL and return cleaned main-content
    text. Backed by httpx + BeautifulSoup; respects redirect limits and
    truncates oversized bodies to keep responses LLM-friendly.
  * ``discover_companies`` — composite: turn a free-form vertical
    description into a ranked list of candidate company names. Used by
    the leads-list pipeline (Luna → 'find me enterprise old-fashioned
    consolidated companies similar to Levi's and Integral Development
    Corp') and by the prospect_vertical A2A pattern.

Why this module is needed: the platform's existing 'search' tools
(``search_meta_ad_library``, ``search_jira_issues``,
``search_knowledge``) are all domain-specific. There was no general
web-search primitive, which blocked any agent task that started with
'find companies / articles / news about X'. Plugging that gap unlocks
the sales-prospecting + market-intelligence vertical end-to-end.

Bot-detection caveat: DuckDuckGo's HTML endpoint occasionally serves
captchas when traffic from a tenant pod looks bursty. Tavily is the
production path; the DDG fallback is a 'something is better than
nothing' net.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _get_api_base_url() -> str:
    return os.getenv("API_BASE_URL", "http://api:8000")


def _get_internal_key() -> str:
    return os.getenv("API_INTERNAL_KEY") or os.getenv("MCP_API_KEY", "")


async def _fetch_tavily_credential(tenant_id: str) -> Optional[str]:
    """Look up the tenant's Tavily API key from the credential vault.

    Returns None if no credential is configured (we fall back to DDG).
    Mirrors how other ``*_credentials`` helpers in this package fetch
    OAuth tokens / API keys through the api's internal credential
    endpoint.
    """
    if not tenant_id:
        return None
    api_base = _get_api_base_url()
    internal_key = _get_internal_key()
    headers = {"X-Internal-Key": internal_key}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{api_base}/api/v1/integration-configs/internal/credential",
                params={"tenant_id": tenant_id, "integration_name": "tavily"},
                headers=headers,
            )
        if resp.status_code != 200:
            return None
        body = resp.json()
        # The credential endpoint returns the decrypted secret under
        # `api_key` for token-style integrations.
        return body.get("api_key") or body.get("token")
    except Exception as e:
        logger.debug("tavily credential lookup failed: %s", e)
        return None


async def _tavily_search(
    api_key: str,
    query: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Call the Tavily search API. Returns normalised result rows."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"tavily search HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return [
        {
            "title": r.get("title", "").strip(),
            "url": r.get("url", "").strip(),
            "snippet": r.get("content", "").strip()[:500],
            "source": "tavily",
        }
        for r in data.get("results", [])
    ]


async def _duckduckgo_html_search(query: str, max_results: int) -> List[Dict[str, str]]:
    """Scrape the DDG HTML endpoint as a fallback. No API key required.

    Sets a UA so the result page renders consistently. If DDG serves a
    captcha (which it does intermittently from datacenter IPs), this
    returns an empty list — callers should treat that as 'no signal'
    rather than an error so the upstream agent can degrade gracefully.
    """
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        out: List[Dict[str, str]] = []
        # Result anchors in DDG HTML have the `.result__a` class. Their
        # `href` is sometimes wrapped in a redirector — strip the prefix.
        for a in soup.select("a.result__a")[:max_results]:
            href = a.get("href", "").strip()
            # DDG redirector: /l/?kh=-1&uddg=<actual-url-urlencoded>
            if href.startswith("//duckduckgo.com/l/") or "uddg=" in href:
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    from urllib.parse import unquote
                    href = unquote(m.group(1))
            title = a.get_text(strip=True)
            # Snippet sits in the sibling .result__snippet on the same row.
            parent = a.find_parent(class_=re.compile(r"result"))
            snippet_el = parent.select_one(".result__snippet") if parent else None
            snippet = snippet_el.get_text(strip=True)[:500] if snippet_el else ""
            if title and href:
                out.append(
                    {"title": title, "url": href, "snippet": snippet, "source": "duckduckgo"}
                )
        return out
    except Exception as e:
        logger.warning("DuckDuckGo fallback failed: %s", e)
        return []


# ── MCP tools ────────────────────────────────────────────────────────


@mcp.tool()
async def web_search(
    query: str,
    max_results: int = 10,
    tenant_id: str = "",
    ctx: Context = None,
) -> Dict[str, Any]:
    """Search the web for information matching ``query``.

    Tries Tavily first (best quality, requires the tenant to have a
    Tavily credential connected); falls back to DuckDuckGo HTML scrape
    when Tavily isn't configured.

    Args:
        query: Free-text search query. Phrase queries work; operators
            (site:, intitle:, etc.) are passed through but only Tavily
            interprets them.
        max_results: Cap on returned rows. Default 10; the upstream
            providers cap at ~20.
        tenant_id: Tenant UUID. Auto-resolved from the MCP context when
            omitted (the normal path — only set explicitly for testing).

    Returns:
        ``{"results": [{title, url, snippet, source}, ...], "provider":
        "tavily"|"duckduckgo"|"none", "query": <echo>}``. Empty results
        list when both providers return nothing (e.g. DDG captcha).
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    if not query or not query.strip():
        return {"error": "query is required", "results": [], "provider": "none"}
    query = query.strip()
    max_results = max(1, min(max_results, 20))

    api_key = await _fetch_tavily_credential(tid) if tid else None
    if api_key:
        try:
            results = await _tavily_search(api_key, query, max_results)
            return {"results": results, "provider": "tavily", "query": query}
        except Exception as e:
            logger.warning("tavily search failed, falling back to DDG: %s", e)

    results = await _duckduckgo_html_search(query, max_results)
    return {
        "results": results,
        "provider": "duckduckgo" if results else "none",
        "query": query,
    }


@mcp.tool()
async def fetch_url(
    url: str,
    max_chars: int = 8000,
    tenant_id: str = "",
    ctx: Context = None,
) -> Dict[str, Any]:
    """Fetch ``url`` and return cleaned main-content text.

    Drops nav / footer / script / style blocks and returns the textual
    body. Truncates to ``max_chars`` so the response stays
    LLM-context-friendly — callers wanting the raw HTML should use
    ``connectors.query_data_source`` against a generic REST connector
    instead.

    Args:
        url: Fully-qualified http/https URL.
        max_chars: Body truncation cap. Default 8000 (~2000 tokens).
        tenant_id: Unused today; here to keep the contract uniform with
            other tenant-scoped tools and reserved for future caching
            keyed by tenant_id.

    Returns:
        ``{"url": <final_url_after_redirects>, "status": <http_code>,
        "title": <html_title or "">, "text": <cleaned_body>,
        "char_count": <len_pre_truncation>, "truncated": <bool>}`` or
        ``{"error": ...}``.
    """
    if not url or not url.strip():
        return {"error": "url is required"}
    if not url.startswith(("http://", "https://")):
        return {"error": f"url must be http(s); got {url[:80]}"}
    # SSRF guard: reject obvious internal targets. The cluster runs
    # mcp-tools alongside api / postgres / redis on the same docker
    # network; an LLM-emitted `http://api:8000/api/v1/...` would
    # otherwise reach the API as the internal client. Block any host
    # without a TLD (single label) and known internal hosts.
    host = (urlparse(url).hostname or "").lower()
    if not host or "." not in host or host in {"api", "postgres", "redis", "mcp-tools"}:
        return {"error": f"refusing to fetch internal host: {host or '<empty>'}"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AgentProvision/1.0; "
            "+https://agentprovision.com)"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        return {"error": f"fetch failed: {e}", "url": url}

    final_url = str(resp.url)
    content_type = resp.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        # Non-HTML — return the body trimmed without bs4 parsing.
        text = resp.text[:max_chars]
        return {
            "url": final_url,
            "status": resp.status_code,
            "title": "",
            "text": text,
            "char_count": len(resp.text),
            "truncated": len(resp.text) > max_chars,
            "content_type": content_type,
        }

    soup = BeautifulSoup(resp.text, "html.parser")
    # Strip elements that never carry main content. The order matters
    # only marginally — `script` / `style` are the biggest offenders.
    for tag_name in ("script", "style", "nav", "footer", "header", "aside", "form", "noscript"):
        for el in soup.find_all(tag_name):
            el.decompose()

    title_el = soup.find("title")
    title = title_el.get_text(strip=True) if title_el else ""

    # Prefer <main> / <article> when present — they typically wrap the
    # readable content on modern marketing sites and news outlets.
    body_root = soup.find("main") or soup.find("article") or soup.body or soup
    text = body_root.get_text("\n", strip=True)
    # Collapse runs of blank lines so the truncated window holds more signal.
    text = re.sub(r"\n{3,}", "\n\n", text)

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return {
        "url": final_url,
        "status": resp.status_code,
        "title": title,
        "text": text,
        "char_count": len(text) if not truncated else max_chars,
        "truncated": truncated,
        "content_type": content_type,
    }


@mcp.tool()
async def discover_companies(
    vertical_description: str,
    count: int = 10,
    tenant_id: str = "",
    ctx: Context = None,
) -> Dict[str, Any]:
    """Find companies that match a free-form vertical description.

    Composes ``web_search`` with a handful of derived queries to assemble
    a deduplicated list of candidate company names. Designed for the
    sales-prospecting use case — the user describes the target ICP
    (e.g. 'enterprise old-fashioned consolidated apparel and
    manufacturing companies') and gets back a starter list to seed the
    knowledge graph + lead-scoring pipeline.

    This intentionally doesn't call ``create_entity`` itself — keeping
    discovery and persistence separate lets the agent decide which
    candidates are worth keeping, which need enrichment, and which to
    discard. The companion ``qualify_lead`` tool consumes the output.

    Args:
        vertical_description: Free-text description of the target ICP.
        count: Cap on companies returned. Default 10.
        tenant_id: Auto-resolved from MCP context when omitted.

    Returns:
        ``{"companies": [{name, domain, source_url, snippet}, ...],
        "queries_run": [...], "tenant_id": <id>}``. Empty list when web
        search returned nothing.
    """
    tid = resolve_tenant_id(ctx) or tenant_id
    desc = (vertical_description or "").strip()
    if not desc:
        return {"error": "vertical_description is required", "companies": []}
    count = max(1, min(count, 50))

    # Three deterministic query expansions. The first is the user
    # description verbatim; the others slot it into well-known
    # company-discovery phrasings that tend to surface curated lists
    # ("top companies in X", "publicly traded X companies"). We avoid
    # an LLM expansion here because (a) it doubles cost and (b) the
    # gemma4 host isn't always reachable from inside mcp-tools.
    queries = [
        desc,
        f"top companies {desc}",
        f"largest publicly traded companies {desc}",
    ]

    seen_domains: set[str] = set()
    companies: List[Dict[str, str]] = []

    for q in queries:
        try:
            search_result = await web_search(
                query=q, max_results=count, tenant_id=tid, ctx=ctx
            )
        except Exception as e:
            logger.warning("web_search failed for query %r: %s", q, e)
            continue
        for r in search_result.get("results", []):
            url = r.get("url") or ""
            host = (urlparse(url).hostname or "").lower()
            if not host:
                continue
            # Strip a leading 'www.' so 'www.acme.com' and 'acme.com'
            # dedup to one row.
            host = host.removeprefix("www.")
            # Skip aggregator domains that pollute the candidate list.
            # The agent can revisit aggregator pages explicitly via
            # fetch_url when the user wants to mine a curated list.
            if host in {
                "wikipedia.org",
                "en.wikipedia.org",
                "linkedin.com",
                "twitter.com",
                "x.com",
                "youtube.com",
                "reddit.com",
                "duckduckgo.com",
                "google.com",
                "bing.com",
            }:
                continue
            if host in seen_domains:
                continue
            seen_domains.add(host)
            # The 'name' is a best-effort derivation: title prefix
            # before the first '|' / '–' / ' - ' or the domain's
            # first label, capitalised. The agent will overwrite this
            # with a clean canonical name when it persists.
            raw_title = r.get("title", "")
            name = re.split(r"\s*[|\-–—:]\s*", raw_title, maxsplit=1)[0].strip()
            if not name:
                name = host.split(".")[0].capitalize()
            companies.append(
                {
                    "name": name,
                    "domain": host,
                    "source_url": url,
                    "snippet": r.get("snippet", "")[:300],
                }
            )
            if len(companies) >= count:
                break
        if len(companies) >= count:
            break

    return {
        "companies": companies,
        "queries_run": queries,
        "tenant_id": tid,
    }


# Tool registration happens via the @mcp.tool() decorators above —
# importing this module from src/mcp_tools/__init__.py is enough.
