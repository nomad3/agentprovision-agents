# Web Scraper & MCP Server Integration Design

## Overview

Add Playwright-based web scraping to the AgentProvision MCP server for lead generation, market signals, and knowledge graph enrichment. Fix the MCP server to be production-ready (Helm chart, working endpoints, Playwright Docker image) and add generic scraping tools that the ADK web_researcher agent can use.

## Architecture

```
ADK Server (port 8080)
  ├── agentprovision_supervisor (root agent)
  │   ├── data_analyst
  │   ├── report_generator
  │   ├── knowledge_manager
  │   └── web_researcher (NEW)
  │       Tools: scrape_webpage, scrape_structured_data, search_and_scrape
  │
  ↓ httpx (X-API-Key + X-Tenant-ID)
  │
MCP Server (port 8000, exposed 8086)
  ├── /tools/postgres_tools.py   (existing - PostgreSQL queries)
  ├── /tools/postgres.py           (existing - PostgreSQL connections)
  ├── /tools/ingestion.py          (existing - data ingestion)
  └── /tools/web_scraper.py        (NEW - Playwright scraping)
       ├── scrape_webpage(url, selectors, wait_for)
       ├── scrape_structured_data(url, schema)
       └── search_and_scrape(query, engine, max_results)
  │
  ├── /services/browser_service.py (NEW - Playwright lifecycle)
  │    Ported from dentalerp: anti-detection, retry, circuit breaker
  │
  └── /scrapers/base_page.py       (NEW - page object base class)
       Ported from dentalerp: navigate, wait, screenshot, debug artifacts
```

## Data Flow

```
Web Researcher Agent receives task (e.g. "find AI startups hiring in Austin")
  ↓
Agent calls search_and_scrape(query="AI startups Austin hiring", max_results=10)
  ↓
MCP Server: Google search → collect URLs → scrape each with Playwright
  ↓
Returns structured data: [{url, title, content, extracted_data}]
  ↓
Agent calls ADK knowledge tools: create_entity() for each company/person found
  ↓
Knowledge graph populated with leads + market signals
  ↓
Lead scoring agents can query the graph for ranked prospects
```

## Components

### 1. MCP Server Fixes (make production-ready)

- **Dockerfile**: Switch to `mcr.microsoft.com/playwright/python:v1.41.0-jammy` base
- **Helm chart**: Create `helm/values/agentprovision-mcp.yaml` (matches ADK pattern)
- **server.py**: Fix stub endpoints, add real health check
- **deploy-all.yaml**: Add MCP build+deploy job

### 2. Playwright Browser Service (ported from dentalerp)

Reuse from `dentalerp/mcp-server/src/scrapers/dental_intel/`:
- Anti-detection args (disable-blink-features, custom user agent, webdriver masking)
- Browser context config (viewport 1920x1080, locale, timezone)
- Retry with exponential backoff (from `utils/retry.py`)
- Circuit breaker pattern
- Screenshot/HTML debug artifacts

New generic capabilities:
- Browser pool (reuse browsers across requests)
- Configurable timeouts per request
- Content extraction (text, links, images, structured data)
- Stealth mode toggle

### 3. Web Scraper Tools

**`scrape_webpage(url, selectors, wait_for, extract_links, timeout)`**
- Navigate to URL with Playwright
- Wait for selectors or load state
- Extract text content, optionally filtered by CSS selectors
- Return: {url, title, content, links[], meta{}}

**`scrape_structured_data(url, schema, selectors)`**
- Navigate and extract data matching a provided schema
- Schema example: {"company_name": "h1.company", "employees": ".employee-count"}
- Return: {url, data: {company_name: "...", employees: "..."}}

**`search_and_scrape(query, engine, max_results)`**
- Perform Google/Bing search via Playwright
- Scrape top N result pages
- Extract and summarize content from each
- Return: [{url, title, snippet, content}]

### 4. ADK Web Researcher Agent

New sub-agent in `agentprovision_supervisor/web_researcher.py`:
- Model: gemini-2.5-flash
- Tools: scrape_webpage, scrape_structured_data, search_and_scrape
- Also has access to knowledge tools (create_entity, find_entities) for storing results
- Instructions: research companies, extract contacts, identify market signals, store in knowledge graph

### 5. Deployment

- Helm values follow the ADK pattern (Cloud SQL proxy sidecar, external secrets, health probes)
- Dockerfile uses Playwright base image (~1.5GB, includes Chromium)
- Resource requests: 500m CPU, 1Gi memory (Playwright needs more than typical services)
- Add to deploy-all.yaml workflow

## Reused Components from DentalERP

| Component | Source | Adaptation |
|-----------|--------|------------|
| Browser launch config | `scrapers/dental_intel/scraper.py:44-82` | Make configurable, remove DI-specific |
| Anti-detection args | Same file | Direct reuse |
| Retry decorator | `utils/retry.py` | Direct reuse |
| Circuit breaker | `utils/retry.py` | Direct reuse |
| Base page object | `scrapers/dental_intel/pages/base_page.py` | Genericize navigation |
| Debug artifacts | `scraper.py` screenshot/HTML methods | Direct reuse |
| Dockerfile base | `Dockerfile` (Playwright image) | Adapt for ST deps |

## Files to Create/Modify

### New Files
1. `apps/mcp-server/src/tools/web_scraper.py` - 3 scraping tool functions
2. `apps/mcp-server/src/services/browser_service.py` - Playwright lifecycle manager
3. `apps/mcp-server/src/scrapers/__init__.py`
4. `apps/mcp-server/src/scrapers/base_page.py` - Generic page object
5. `apps/mcp-server/src/utils/retry.py` - Retry + circuit breaker (from dentalerp)
6. `apps/adk-server/agentprovision_supervisor/web_researcher.py` - New agent
7. `apps/adk-server/tools/web_tools.py` - ADK tool wrappers calling MCP
8. `helm/values/agentprovision-mcp.yaml` - Helm values

### Modified Files
1. `apps/mcp-server/Dockerfile` - Playwright base image
2. `apps/mcp-server/pyproject.toml` - Add playwright dependency
3. `apps/mcp-server/src/server.py` - Fix stubs, add scraper endpoints
4. `apps/adk-server/agentprovision_supervisor/agent.py` - Add web_researcher sub-agent
5. `apps/adk-server/services/postgres_client.py` - Add web scraper client methods
6. `apps/adk-server/requirements.txt` - No changes needed (uses httpx)
7. `.github/workflows/deploy-all.yaml` - Add MCP build+deploy
