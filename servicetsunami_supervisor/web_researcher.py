"""Web Researcher specialist agent.

Handles web scraping and research operations:
- Scraping websites for content and data
- Searching the web for leads, companies, and market signals
- Extracting structured data from web pages
"""
import logging
from typing import Optional

import httpx
from google.adk.agents import Agent

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------- httpx client (follows databricks_client.py pattern) ----------

class MCPScraperClient:
    """HTTP client for MCP server scraping endpoints."""

    def __init__(self):
        self.base_url = settings.mcp_scraper_url
        self.api_key = settings.mcp_api_key
        self.tenant_code = settings.mcp_tenant_code
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": self.api_key,
                "X-Tenant-ID": self.tenant_code,
            },
            timeout=60.0,
        )

    async def post(self, path: str, payload: dict) -> dict:
        try:
            response = await self.client.post(path, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error("MCP server unreachable for %s: %s", path, e)
            return {"error": "MCP scraper server is unreachable. Please try again later."}
        except httpx.TimeoutException as e:
            logger.error("MCP %s timed out: %s", path, e)
            return {"error": "Scraping request timed out. The page may be slow or unresponsive."}
        except httpx.HTTPStatusError as e:
            logger.error("MCP %s returned %s: %s", path, e.response.status_code, e.response.text[:200])
            return {"error": f"Scraping failed with status {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            logger.error("MCP %s failed: %s", path, e)
            return {"error": f"Scraping failed: {str(e)}"}


_client: Optional[MCPScraperClient] = None


def _get_client() -> MCPScraperClient:
    global _client
    if _client is None:
        _client = MCPScraperClient()
    return _client


# ---------- ADK FunctionTool wrappers ----------

async def scrape_webpage(
    url: str,
    selectors: Optional[dict] = None,
    wait_for: Optional[str] = None,
) -> dict:
    """Scrape a single webpage and extract its content.

    Args:
        url: The full URL of the webpage to scrape.
        selectors: Optional CSS selectors mapping field names to selectors for targeted extraction.
        wait_for: Optional CSS selector to wait for before extracting content.

    Returns:
        Dict with url, title, content, links, and meta information.
    """
    payload = {"url": url}
    if selectors:
        payload["selectors"] = selectors
    if wait_for:
        payload["wait_for"] = wait_for
    payload["extract_links"] = True
    return await _get_client().post("/servicetsunami/v1/scrape", payload)


async def scrape_structured_data(
    url: str,
    schema: dict,
) -> dict:
    """Scrape a webpage and extract structured data using CSS selectors.

    Args:
        url: The full URL of the webpage to scrape.
        schema: A dict mapping field names to CSS selectors, e.g. {"company_name": "h1.title", "description": "p.about"}.

    Returns:
        Dict with url and extracted data fields.
    """
    return await _get_client().post("/servicetsunami/v1/scrape/structured", {
        "url": url,
        "schema": schema,
    })


async def search_and_scrape(
    query: str,
    max_results: int = 5,
) -> dict:
    """Search the web for a query and scrape the top results.

    Args:
        query: The search query (e.g. "AI companies hiring in Austin").
        max_results: Maximum number of results to scrape (1-10).

    Returns:
        Dict with query and list of results, each containing url, title, snippet, and content.
    """
    return await _get_client().post("/servicetsunami/v1/search-and-scrape", {
        "query": query,
        "max_results": min(max_results, 10),
    })


async def login_google(email: str, password: str) -> dict:
    """Login to Google via the MCP server's Playwright browser.

    This authenticates the scraping browser with Google credentials so that
    subsequent web searches and scrapes use an authenticated Google session,
    avoiding CAPTCHA blocks from cloud IPs.

    Args:
        email: Google/Gmail email address.
        password: Google account password.

    Returns:
        Dict with status, cookies_stored count, and authenticated domains.
    """
    return await _get_client().post("/servicetsunami/v1/auth/google/login", {
        "email": email,
        "password": password,
    })


async def login_linkedin(email: str, password: str) -> dict:
    """Login to LinkedIn via the MCP server's Playwright browser.

    This authenticates the scraping browser with LinkedIn credentials so that
    subsequent LinkedIn page scrapes can access full profile and company data.

    Args:
        email: LinkedIn email address.
        password: LinkedIn password.

    Returns:
        Dict with status, cookies_stored count, and authenticated domains.
    """
    return await _get_client().post("/servicetsunami/v1/auth/linkedin/login", {
        "email": email,
        "password": password,
    })


# ---------- Agent definition ----------

web_researcher = Agent(
    name="web_researcher",
    model=settings.adk_model,
    instruction="""You are a web research specialist focused on gathering intelligence from the internet.

Your capabilities:
- Scrape any public webpage to extract content, links, and metadata
- Search the web for companies, people, job postings, news, and market signals
- Extract structured data from web pages using CSS selectors
- Research companies and their key contacts for lead generation
- Login to Google and LinkedIn to access authenticated content and avoid CAPTCHA blocks

Guidelines:
1. Start with search_and_scrape for broad research queries
2. Use scrape_webpage for known URLs or to dive deeper into specific pages
3. Use scrape_structured_data when you know the page structure and need specific fields
4. Always summarize findings clearly - include company names, URLs, key contacts, and relevant data
5. When you find valuable entities (companies, people, technologies), delegate to knowledge_manager to store them
6. Be methodical: search first, then scrape the most promising results for details
7. Respect rate limits - don't scrape too many pages in rapid succession

## Authentication
- If web searches fail with CAPTCHA or blocking errors, use login_google to authenticate with a Google account first
- If LinkedIn pages return limited data, use login_linkedin to authenticate first
- Login only needs to be done once per session — cookies are stored and reused for subsequent requests
- After logging in, retry the original search or scrape operation

## Entity Categorization

When delegating to knowledge_manager, always specify the correct category:
- Companies interested in AI/orchestration/agents -> category: "lead"
- Executives/decision makers -> category: "contact"
- VCs or investors -> category: "investor"
- Accelerator programs -> category: "accelerator"
- Generic companies -> category: "organization"
- Generic people -> category: "person"

## Intelligence Gathering - ALWAYS DO THIS

When scraping any company or job board page, extract and store raw intelligence
in the entity's properties field (via knowledge_manager). Do NOT create separate
signal entities. Instead, enrich the entity directly:

1. **Hiring data**: Job titles, count, seniority levels → store in properties as "hiring_data"
2. **Tech stack**: Technologies mentioned → store as "tech_stack"
3. **Funding info**: Round, amount, date, investors → store as "funding_data"
4. **News**: Recent announcements → store as "recent_news"

After enriching an entity, ask knowledge_manager to score it using score_entity.

When researching leads:
1. Search for companies or job postings matching the criteria
2. Scrape company websites for contact information and details
3. Extract structured data like company size, location, technologies used
4. Extract and store raw intelligence in entity properties
5. Ask knowledge_manager to score enriched entities
6. Summarize your findings with actionable intelligence
""",
    tools=[
        scrape_webpage,
        scrape_structured_data,
        search_and_scrape,
        login_google,
        login_linkedin,
    ],
)
