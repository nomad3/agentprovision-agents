# Marketing Intelligence & Ads Platform Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Luna (and each tenant) a marketing co-pilot that monitors competitors, manages ad campaigns across Meta/Google/TikTok, and delivers actionable intelligence from a business owner's perspective.

**Architecture:** Reuse the existing knowledge graph for competitor entities/observations, add ad platform OAuth integrations to the registry, create new ADK tools for ads + competitor monitoring, and add a Temporal workflow for scheduled competitor tracking. New `marketing_analyst` sub-agent joins the `marketing_team`.

**Tech Stack:** Google ADK agents, Temporal workflows, Meta Marketing API, Google Ads API, TikTok Marketing API, Meta Ad Library (public), Google Ads Transparency (public), MCP scraper for web research.

---

## Phase 1: Marketing Intelligence + Ad Platform Integration

### 1. Ad Platform Integrations

Three OAuth integrations added to the registry (same pattern as Gmail/GitHub):

**Meta Ads** (OAuth2 via Facebook Login)
- Scopes: `ads_management`, `ads_read`, `read_insights`
- Tools: `list_meta_campaigns`, `get_meta_campaign_insights`, `create_meta_campaign`, `update_meta_campaign`, `pause_meta_campaign`, `list_meta_adsets`, `get_meta_ad_creatives`
- Public: `search_meta_ad_library(query, country)` — no auth needed, used for competitor intel

**Google Ads** (OAuth2 via Google)
- Tools: `list_google_campaigns`, `get_google_campaign_metrics`, `create_google_campaign`, `update_google_campaign`, `pause_google_campaign`, `get_google_keyword_performance`
- Public: `search_google_ads_transparency(advertiser)` — for competitor tracking

**TikTok Ads** (OAuth2 via TikTok Business Center)
- Tools: `list_tiktok_campaigns`, `get_tiktok_campaign_insights`, `create_tiktok_campaign`, `update_tiktok_campaign`, `pause_tiktok_campaign`
- Public: `search_tiktok_creative_center(keyword)` — for competitor creative research

### 2. Competitor Monitoring System

**Data model** (reuses knowledge graph):
- Competitors are entities: `category="competitor"`, properties = `{website_url, facebook_url, instagram_url, tiktok_url, google_ads_advertiser_id, monitor_frequency}`
- Relations: `competes_with` between tenant's company entity and competitor
- Observations: `record_observation()` stores each monitoring cycle's findings

**Competitor tools** (`apps/adk-server/tools/competitor_tools.py`):
- `add_competitor(name, website, socials, ad_ids, monitor_frequency)` — creates entity + relation + starts monitoring
- `remove_competitor(name)` — removes entity, stops monitoring
- `get_competitor_report(name)` — pulls latest observations, ad activity, social stats
- `compare_campaigns(competitor_name)` — compares their ad performance vs. yours

### 3. CompetitorMonitorWorkflow (Temporal)

Queue: `servicetsunami-orchestration` (same as InboxMonitor)
Pattern: `continue_as_new` per-tenant, configurable frequency (daily/weekly per competitor)

Each cycle:
1. `fetch_competitors` — knowledge graph query for `category="competitor"` entities
2. `scrape_competitor_activity` — website, social profiles via MCP scraper
3. `check_ad_libraries` — Meta Ad Library API, Google Ads Transparency, TikTok Creative Center
4. `analyze_changes` — LLM diff vs. previous observations
5. `store_observations` — `record_observation()` on each competitor entity
6. `create_notifications` — proactive alerts ("Competitor X launched new Meta campaign targeting...")
7. `continue_as_new` — next cycle

### 4. Marketing Team Agent Enhancement

**Current**: `marketing_team` has `web_researcher` + `knowledge_manager`

**New**: Add `marketing_analyst` sub-agent

**marketing_analyst** agent:
- Tools: all `ads_tools` (Meta/Google/TikTok read+write) + `competitor_tools` + knowledge graph tools
- Pulls campaign performance across all ad platforms
- Compares your metrics vs. competitor activity from observations
- Suggests campaign adjustments based on competitor intel
- Executes campaign changes when user approves

**Updated routing in marketing_team**:
- Web scraping, internet research, company discovery → `web_researcher`
- Campaign metrics, ad management, competitor analysis → `marketing_analyst`
- Store/retrieve research findings, entities → `knowledge_manager`

**Root supervisor routing**:
- "Monitor competitor X", "add competitor", "competitor briefing" → `personal_assistant` (Luna manages directly via competitor_tools)
- "Campaign performance", "ad analytics", "adjust my Meta campaign" → `marketing_team` → `marketing_analyst`

### 5. Data Flow

```
Tenant configures competitor via Luna
  → entity created (category="competitor", properties={urls, socials, frequency})
  → relation created (competes_with)
  → CompetitorMonitorWorkflow started per-tenant

Every cycle:
  1. fetch_competitors → knowledge graph
  2. scrape_competitor_activity → MCP scraper
  3. check_ad_libraries → public APIs
  4. analyze_changes → LLM diff
  5. store_observations → knowledge graph
  6. create_notifications → notification system
  7. continue_as_new → next cycle

User asks about own campaigns:
  → marketing_team → marketing_analyst
  → ads_tools fetch from Meta/Google/TikTok APIs
  → compare with competitor observations
  → actionable recommendations
```

### 6. New Files

- `apps/adk-server/tools/ads_tools.py` — Meta/Google/TikTok API tools (~15 functions)
- `apps/adk-server/tools/competitor_tools.py` — add/remove/report competitor (~4 functions)
- `apps/adk-server/servicetsunami_supervisor/marketing_analyst.py` — new sub-agent
- `apps/api/app/workflows/competitor_monitor.py` — Temporal workflow + activities
- Integration registry entries for meta_ads, google_ads, tiktok_ads
- Helm secrets for new OAuth client IDs/secrets

---

## Phase 2: AI Content Creation (Future)

Out of scope for Phase 1, but noted for planning:

- **AI Content Generation**: Text (marketing copy, social posts), images (via image generation APIs), short videos (Highfield/Runway style)
- **Publishing**: Post directly to Meta, TikTok, Google via same OAuth tokens from Phase 1
- **Content Calendar**: Schedule and manage upcoming posts through Luna
- **A/B Testing**: Generate multiple creative variants, track which performs best

Phase 1 OAuth tokens will be reused for publishing in Phase 2.
