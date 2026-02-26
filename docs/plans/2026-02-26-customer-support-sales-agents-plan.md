# Customer Support & Sales Agents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add customer_support and sales_agent sub-agents to the ADK supervisor, with shared connector query tool, sales automation tools, a Temporal follow-up workflow, a WhatsApp self-message bug fix, and updated wizard templates.

**Architecture:** Two new ADK sub-agents join the existing supervisor. They reuse existing knowledge_tools, data_tools, and the shared chat pipeline. A new `query_data_source` tool bridges agents to tenant-connected databases/APIs. A Temporal `FollowUpWorkflow` handles scheduled sales actions. The WhatsApp service gets a fix so the bot only responds to self-chat or inbound DMs (not messages to friends).

**Tech Stack:** Google ADK (Python), FastAPI, Temporal, SQLAlchemy, httpx, React

---

### Task 1: Fix WhatsApp self-message bug

The bot currently responds to messages the user sends to friends. It should only respond to inbound DMs or self-chat messages.

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py:330-335`

**Step 1: Add chat_jid guard for is_from_me messages**

In `_handle_inbound`, after the group message check (line 328) and before the self-message block (line 330), add a check that skips messages where the user is messaging someone else:

```python
        # Skip messages the user sends to other contacts — only process:
        # - is_from_me=False: someone DMing the bot's number
        # - is_from_me=True AND chat is self-chat: user messaging themselves (personal bot)
        if is_from_me and chat_jid != sender_jid:
            return
```

This replaces the existing block at lines 330-335. The full replacement should be:

```python
        # Skip messages the user sends to other contacts — only process self-chat or inbound DMs
        if is_from_me and chat_jid != sender_jid:
            return

        # Skip bot echo replies in self-chat
        if is_from_me:
            sent_ids = self._sent_message_ids.get(key, set())
            if msg_id and msg_id in sent_ids:
                sent_ids.discard(msg_id)
                return
```

**Step 2: Commit**

```bash
git add apps/api/app/services/whatsapp_service.py
git commit -m "fix: only respond to self-chat and inbound DMs on WhatsApp

Skip messages the user sends to other contacts (chat_jid != sender_jid).
Previously the bot responded to all is_from_me messages that weren't
bot echoes, including messages sent to friends."
```

---

### Task 2: Create `query_data_source` connector tool

This tool lets agents query tenant-connected data sources (PostgreSQL, MySQL, Snowflake, REST APIs) in real-time. It calls back to the FastAPI API which already has connector credential storage and query execution.

**Files:**
- Create: `apps/adk-server/tools/connector_tools.py`

**Step 1: Write the tool**

```python
"""Connector tools for querying tenant data sources.

Bridges ADK agents to tenant-connected databases and APIs via the
FastAPI backend's existing connector infrastructure.
"""
import logging
from typing import Optional

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=60.0,
        )
    return _http_client


async def query_data_source(
    tenant_id: str,
    query: str,
    connector_id: Optional[str] = None,
    connector_type: Optional[str] = None,
) -> dict:
    """Query a tenant's connected data source (database, API, or warehouse).

    Executes a read-only SQL query or API call against a tenant's configured
    connector. Use this to look up customer records, order status, inventory,
    product catalog, or any data the tenant has connected.

    Args:
        tenant_id: Tenant context for isolation.
        query: SQL SELECT query for databases, or search term for REST APIs.
        connector_id: Specific connector UUID to query. If omitted, uses the
            first active connector matching connector_type (or any active one).
        connector_type: Filter by type: postgres, mysql, snowflake, databricks, api.
            Ignored if connector_id is provided.

    Returns:
        Dict with columns, rows, row_count, and connector metadata.
        On error, returns {error: str}.
    """
    client = _get_http_client()
    try:
        # If no connector_id, discover one
        if not connector_id:
            resp = await client.get(
                "/api/v1/connectors",
                headers={"X-Internal-Key": settings.mcp_api_key},
                params={"tenant_id": tenant_id},
            )
            resp.raise_for_status()
            connectors = resp.json()

            # Filter active connectors
            active = [c for c in connectors if c.get("status") == "active"]
            if connector_type:
                active = [c for c in active if c.get("type") == connector_type]
            if not active:
                return {"error": f"No active connectors found for tenant (type={connector_type})"}
            connector_id = active[0]["id"]

        # Execute query via the data source query endpoint
        resp = await client.post(
            f"/api/v1/data-sources/{connector_id}/query",
            headers={"X-Internal-Key": settings.mcp_api_key},
            json={"query": query, "tenant_id": tenant_id},
        )
        resp.raise_for_status()
        result = resp.json()
        return {
            "success": True,
            "columns": list(result[0].keys()) if result else [],
            "rows": result[:100],  # Cap at 100 rows
            "row_count": len(result),
            "connector_id": connector_id,
        }
    except httpx.HTTPStatusError as e:
        logger.error("query_data_source failed: %s %s", e.response.status_code, e.response.text[:300])
        return {"error": f"Query failed with status {e.response.status_code}"}
    except Exception as e:
        logger.error("query_data_source error: %s", e)
        return {"error": f"Query failed: {str(e)}"}
```

**Step 2: Commit**

```bash
git add apps/adk-server/tools/connector_tools.py
git commit -m "feat: add query_data_source tool for live connector queries

Bridges ADK agents to tenant-connected databases and APIs via the
existing FastAPI connector infrastructure. Supports auto-discovery
of active connectors by type."
```

---

### Task 3: Create sales tools

LLM-powered sales automation tools that use existing knowledge graph infrastructure.

**Files:**
- Create: `apps/adk-server/tools/sales_tools.py`

**Step 1: Write the sales tools**

```python
"""Sales automation tools.

LLM-powered tools for lead qualification, outreach drafting, pipeline
management, proposal generation, and follow-up scheduling. All tools
operate on entities in the knowledge graph.
"""
import logging
import uuid
from typing import Optional
from datetime import datetime

import httpx

from services.knowledge_graph import get_knowledge_service
from tools.knowledge_tools import _resolve_tenant_id
from config.settings import settings

logger = logging.getLogger(__name__)

_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=30.0,
        )
    return _http_client


async def qualify_lead(
    entity_id: str,
    tenant_id: str,
) -> dict:
    """Qualify a lead using BANT framework (Budget, Authority, Need, Timeline).

    Fetches entity context from the knowledge graph, evaluates qualification
    criteria, and updates the entity properties with qualification results.

    Args:
        entity_id: UUID of the lead entity to qualify.
        tenant_id: Tenant context.

    Returns:
        Dict with budget, authority, need, timeline assessments, overall
        qualified boolean, and summary.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    kg = get_knowledge_service()
    entity = await kg.get_entity(entity_id, include_relations=True)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    # Build qualification from entity properties
    props = entity.get("properties", {})
    qualification = {
        "budget": _assess_budget(props),
        "authority": _assess_authority(props),
        "need": _assess_need(props),
        "timeline": _assess_timeline(props),
    }
    scores = [v["score"] for v in qualification.values()]
    avg_score = sum(scores) / len(scores) if scores else 0
    qualified = avg_score >= 50

    qualification["qualified"] = qualified
    qualification["score"] = round(avg_score)
    qualification["summary"] = (
        f"{'Qualified' if qualified else 'Not qualified'} "
        f"(score: {round(avg_score)}/100)"
    )

    # Update entity with qualification result
    updated_props = {**props, "qualification": qualification, "qualified": qualified}
    if qualified and not props.get("pipeline_stage"):
        updated_props["pipeline_stage"] = "qualified"

    await kg.update_entity(
        entity_id=entity_id,
        updates={"properties": updated_props},
        reason="BANT qualification",
    )

    return qualification


def _assess_budget(props: dict) -> dict:
    funding = props.get("funding_data", {})
    has_funding = bool(funding.get("total_raised") or funding.get("last_round"))
    return {
        "score": 70 if has_funding else 30,
        "evidence": f"Funding: {funding.get('total_raised', 'unknown')}",
        "assessment": "Has funding" if has_funding else "Funding unknown",
    }


def _assess_authority(props: dict) -> dict:
    contacts = props.get("contacts", [])
    has_decision_maker = any(
        c.get("role", "").lower() in ("ceo", "cto", "vp", "director", "head", "founder")
        for c in contacts
    ) if contacts else False
    return {
        "score": 80 if has_decision_maker else 40,
        "evidence": f"{len(contacts)} contacts identified",
        "assessment": "Decision maker identified" if has_decision_maker else "No decision maker found",
    }


def _assess_need(props: dict) -> dict:
    hiring = props.get("hiring_data", {})
    tech = props.get("tech_stack", [])
    signals = bool(hiring) or bool(tech)
    return {
        "score": 70 if signals else 30,
        "evidence": f"Hiring: {bool(hiring)}, Tech stack: {len(tech)} items",
        "assessment": "Active signals detected" if signals else "No clear need signals",
    }


def _assess_timeline(props: dict) -> dict:
    news = props.get("recent_news", [])
    has_urgency = len(news) > 0
    return {
        "score": 60 if has_urgency else 30,
        "evidence": f"{len(news)} recent news items",
        "assessment": "Recent activity suggests active timeline" if has_urgency else "No urgency signals",
    }


async def draft_outreach(
    entity_id: str,
    tenant_id: str,
    channel: str = "email",
    tone: str = "professional",
) -> dict:
    """Draft a personalized outreach message for a lead.

    Generates a message based on the entity's properties, qualification
    status, and the specified channel format.

    Args:
        entity_id: UUID of the lead/contact entity.
        tenant_id: Tenant context.
        channel: Message channel - "email", "whatsapp", or "linkedin".
        tone: Message tone - "professional", "casual", or "formal".

    Returns:
        Dict with subject (for email), body, channel, and entity context.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    kg = get_knowledge_service()
    entity = await kg.get_entity(entity_id, include_relations=True)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    name = entity.get("name", "there")
    props = entity.get("properties", {})
    entity_type = entity.get("entity_type", "")
    description = entity.get("description", "")

    # Build context summary for personalization
    context_parts = [f"Company/Contact: {name}"]
    if description:
        context_parts.append(f"About: {description}")
    if props.get("tech_stack"):
        context_parts.append(f"Tech stack: {', '.join(props['tech_stack'][:5])}")
    if props.get("hiring_data"):
        context_parts.append(f"Hiring: {props['hiring_data']}")
    if props.get("qualification"):
        qual = props["qualification"]
        context_parts.append(f"Qualification: {qual.get('summary', 'N/A')}")

    context = "\n".join(context_parts)

    # Channel-specific formatting
    if channel == "email":
        return {
            "channel": "email",
            "subject": f"Quick question for {name}",
            "body": f"Hi {name},\n\n[Personalize based on: {context}]\n\nBest regards",
            "entity_name": name,
            "context": context,
            "note": "This is a draft template. The LLM supervisor should personalize the body using the context provided.",
        }
    elif channel == "whatsapp":
        return {
            "channel": "whatsapp",
            "body": f"Hi {name}! [Personalize based on: {context}]",
            "entity_name": name,
            "context": context,
            "note": "Short, conversational format for WhatsApp.",
        }
    else:
        return {
            "channel": channel,
            "body": f"Hi {name}, [Personalize based on: {context}]",
            "entity_name": name,
            "context": context,
        }


async def update_pipeline_stage(
    entity_id: str,
    new_stage: str,
    tenant_id: str,
    reason: str = "",
) -> dict:
    """Move a lead entity to a new pipeline stage.

    Updates the entity's pipeline_stage property and records the transition
    as an observation for audit trail.

    Args:
        entity_id: UUID of the entity.
        new_stage: Target stage name (e.g., "qualified", "proposal", "closed_won").
        tenant_id: Tenant context.
        reason: Why the stage is changing.

    Returns:
        Dict with entity_id, previous_stage, new_stage, updated_at.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    kg = get_knowledge_service()
    entity = await kg.get_entity(entity_id, include_relations=False)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    props = entity.get("properties", {})
    previous_stage = props.get("pipeline_stage", "none")

    # Update entity
    updated_props = {**props, "pipeline_stage": new_stage}
    # Track stage history
    stage_history = props.get("stage_history", [])
    stage_history.append({
        "from": previous_stage,
        "to": new_stage,
        "reason": reason,
        "at": datetime.utcnow().isoformat(),
    })
    updated_props["stage_history"] = stage_history

    await kg.update_entity(
        entity_id=entity_id,
        updates={"properties": updated_props},
        reason=f"Pipeline stage: {previous_stage} → {new_stage}. {reason}",
    )

    # Record observation for audit
    await kg.record_observation(
        observation_text=f"Pipeline stage changed: {previous_stage} → {new_stage}. {reason}",
        tenant_id=tenant_id,
        observation_type="pipeline_transition",
        source_type="sales_agent",
    )

    return {
        "entity_id": entity_id,
        "entity_name": entity.get("name"),
        "previous_stage": previous_stage,
        "new_stage": new_stage,
        "updated_at": datetime.utcnow().isoformat(),
    }


async def get_pipeline_summary(
    tenant_id: str,
    category: str = "lead",
) -> dict:
    """Get aggregate pipeline metrics across all leads for a tenant.

    Queries knowledge entities to count leads at each pipeline stage
    and calculate basic conversion metrics.

    Args:
        tenant_id: Tenant context.
        category: Entity category to summarize (default: "lead").

    Returns:
        Dict with stages breakdown, total_leads, and stage counts.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    kg = get_knowledge_service()

    # Find all entities in the category
    entities = await kg.find_entities(
        query="*",
        tenant_id=tenant_id,
        entity_types=None,
        limit=500,
        min_confidence=0.0,
    )

    # Filter by category and count stages
    stage_counts = {}
    total = 0
    for entity in entities:
        if entity.get("category") != category:
            continue
        total += 1
        stage = entity.get("properties", {}).get("pipeline_stage", "unassigned")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    stages = [
        {"stage": stage, "count": count}
        for stage, count in sorted(stage_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "total_leads": total,
        "stages": stages,
        "category": category,
    }


async def generate_proposal(
    entity_id: str,
    tenant_id: str,
    product_ids: Optional[list] = None,
) -> dict:
    """Generate a proposal document for a lead based on their profile and products.

    Fetches the lead entity and relevant product/service entities from the
    knowledge graph, then structures a proposal outline.

    Args:
        entity_id: UUID of the lead entity.
        tenant_id: Tenant context.
        product_ids: Optional list of product entity UUIDs. If omitted,
            searches knowledge graph for product entities.

    Returns:
        Dict with title, sections, products, and entity context for the LLM
        to format into a full proposal.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    kg = get_knowledge_service()
    entity = await kg.get_entity(entity_id, include_relations=True)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    # Find products/services
    products = []
    if product_ids:
        for pid in product_ids:
            prod = await kg.get_entity(pid, include_relations=False)
            if prod:
                products.append(prod)
    else:
        products = await kg.find_entities(
            query="product service offering",
            tenant_id=tenant_id,
            limit=10,
            min_confidence=0.0,
        )
        products = [p for p in products if p.get("category") in ("product", "service", None)]

    return {
        "title": f"Proposal for {entity.get('name')}",
        "lead": {
            "name": entity.get("name"),
            "type": entity.get("entity_type"),
            "description": entity.get("description"),
            "properties": entity.get("properties", {}),
        },
        "products": [
            {
                "name": p.get("name"),
                "description": p.get("description"),
                "properties": p.get("properties", {}),
            }
            for p in products[:5]
        ],
        "sections": [
            "Executive Summary",
            "Understanding Your Needs",
            "Proposed Solution",
            "Pricing & Timeline",
            "Next Steps",
        ],
        "note": "This is a structured outline. The LLM should expand each section into full prose based on the lead and product context.",
    }


async def schedule_followup(
    entity_id: str,
    tenant_id: str,
    action: str,
    delay_hours: int = 24,
    message: str = "",
) -> dict:
    """Schedule a follow-up action for a lead via Temporal workflow.

    Creates a delayed task that will execute after the specified number
    of hours. Actions include sending messages, updating pipeline stage,
    or creating reminders.

    Args:
        entity_id: UUID of the entity to follow up with.
        tenant_id: Tenant context.
        action: Action type - "send_whatsapp", "update_stage", or "remind".
        delay_hours: Hours to wait before executing (default: 24).
        message: Message content for send actions, or stage name for update_stage.

    Returns:
        Dict with workflow_id, scheduled_for, action, entity_id.
    """
    client = _get_http_client()
    try:
        resp = await client.post(
            "/api/v1/workflows/followup",
            headers={"X-Internal-Key": settings.mcp_api_key},
            json={
                "entity_id": entity_id,
                "tenant_id": _resolve_tenant_id(tenant_id),
                "action": action,
                "delay_hours": delay_hours,
                "message": message,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("schedule_followup failed: %s", e)
        return {
            "status": "scheduled_locally",
            "entity_id": entity_id,
            "action": action,
            "delay_hours": delay_hours,
            "note": f"Temporal scheduling failed ({e}), follow up manually.",
        }
```

**Step 2: Commit**

```bash
git add apps/adk-server/tools/sales_tools.py
git commit -m "feat: add sales automation tools

qualify_lead (BANT), draft_outreach, update_pipeline_stage,
get_pipeline_summary, generate_proposal, schedule_followup.
All operate on knowledge graph entities."
```

---

### Task 4: Create customer_support agent

**Files:**
- Create: `apps/adk-server/servicetsunami_supervisor/customer_support.py`

**Step 1: Write the agent**

```python
"""Customer Support specialist agent.

Handles inbound customer interactions from WhatsApp and chat:
- FAQ and product inquiries
- Order status and account lookups via connected data sources
- Complaint handling and escalation
- General conversation and greetings
"""
from google.adk.agents import Agent

from tools.knowledge_tools import (
    search_knowledge,
    find_entities,
    record_observation,
)
from tools.connector_tools import query_data_source
from config.settings import settings

customer_support = Agent(
    name="customer_support",
    model=settings.adk_model,
    instruction="""You are a customer support specialist. You handle inbound customer interactions across all channels (WhatsApp, web chat).

IMPORTANT: For the tenant_id parameter in all tools, use the value from the session state.
If you cannot access the session state, use "auto" as tenant_id and the system will resolve it.

Your capabilities:
- Answer questions using the knowledge base (FAQs, product info, policies)
- Look up customer records, order status, and inventory from connected data sources
- Record customer feedback and observations
- Handle general conversation naturally (greetings, small talk, clarifications)

## How to handle requests:

1. **Product/FAQ questions**: Use search_knowledge first. If no result, try find_entities with the product name.
2. **Order/account lookups**: Use query_data_source with a SQL query against the tenant's database. Example: `SELECT * FROM orders WHERE customer_email = 'user@example.com' ORDER BY created_at DESC LIMIT 5`
3. **Complaints/feedback**: Acknowledge the issue empathetically, use record_observation to log it, then try to resolve or escalate.
4. **General conversation**: Respond naturally. Be friendly and helpful. You ARE allowed to have casual conversations.
5. **Unknown questions**: Say you'll look into it and suggest the customer contact support directly. Do NOT make up answers.

## Tone guidelines:
- Be friendly, empathetic, and professional
- Adapt to the customer's language and formality level
- Keep responses concise for WhatsApp (short paragraphs)
- Use the customer's name if known
- Never be defensive about product issues

## Escalation:
If you cannot resolve an issue after 2 attempts, tell the customer you're connecting them with a human agent and record an observation with type "escalation_needed".
""",
    tools=[
        search_knowledge,
        find_entities,
        record_observation,
        query_data_source,
    ],
)
```

**Step 2: Commit**

```bash
git add apps/adk-server/servicetsunami_supervisor/customer_support.py
git commit -m "feat: add customer_support ADK sub-agent

Handles inbound customer interactions via knowledge graph lookup,
connected data source queries, and natural conversation."
```

---

### Task 5: Create sales_agent

**Files:**
- Create: `apps/adk-server/servicetsunami_supervisor/sales_agent.py`

**Step 1: Write the agent**

```python
"""Sales specialist agent.

Handles outbound sales automation and inbound prospect interactions:
- Lead qualification (BANT framework)
- Personalized outreach drafting
- Pipeline stage management
- Proposal generation
- Follow-up scheduling
"""
from google.adk.agents import Agent

from tools.knowledge_tools import (
    search_knowledge,
    find_entities,
    create_entity,
    update_entity,
    get_entity,
    create_relation,
    record_observation,
    score_entity,
)
from tools.connector_tools import query_data_source
from tools.sales_tools import (
    qualify_lead,
    draft_outreach,
    update_pipeline_stage,
    get_pipeline_summary,
    generate_proposal,
    schedule_followup,
)
from config.settings import settings

sales_agent = Agent(
    name="sales_agent",
    model=settings.adk_model,
    instruction="""You are a sales automation specialist. You handle both proactive sales workflows and inbound prospect interactions.

IMPORTANT: For the tenant_id parameter in all tools, use the value from the session state.
If you cannot access the session state, use "auto" as tenant_id and the system will resolve it.

Your capabilities:
- Qualify leads using BANT framework (Budget, Authority, Need, Timeline)
- Draft personalized outreach messages (email, WhatsApp, LinkedIn)
- Manage sales pipeline stages for entities
- Generate proposals from product catalog and lead context
- Schedule follow-up actions via Temporal workflows
- Score leads using configurable rubrics (ai_lead, hca_deal, marketing_signal)
- Query connected CRM/ecommerce data sources for customer intelligence

## Sales workflow:

1. **New lead identified**: Create entity → score with appropriate rubric → qualify → update pipeline stage to "prospect" or "qualified"
2. **Outreach requested**: Get entity context → draft_outreach for specified channel → present draft for approval
3. **Pipeline management**: Use update_pipeline_stage to move leads through the funnel. Always include a reason for the transition.
4. **Proposal requested**: generate_proposal pulls lead + product context from knowledge graph → present structured outline
5. **Follow-up needed**: schedule_followup with delay_hours and action type

## Pipeline stages (default, tenants can customize):
prospect → qualified → proposal → negotiation → closed_won / closed_lost

## When to use which scoring rubric:
- General leads, AI/tech companies → ai_lead (default)
- M&A deals, sell-likelihood → hca_deal
- Marketing engagement, MQL scoring → marketing_signal

## Entity management:
- Before creating a lead, ALWAYS search first to avoid duplicates
- Set category="lead" for companies, category="contact" for people
- Store qualification results, outreach history, and pipeline stage in entity properties
- Link contacts to their companies with create_relation (relation_type="works_at")

## Data source queries:
Use query_data_source to pull customer data from connected databases:
- CRM records: `SELECT * FROM customers WHERE company_name ILIKE '%{name}%'`
- Sales history: `SELECT * FROM orders WHERE customer_id = '{id}' ORDER BY date DESC`
- Pipeline data: `SELECT stage, COUNT(*) FROM deals GROUP BY stage`

Always be data-driven in your recommendations. Back up qualification and scoring with evidence from the knowledge graph and connected data sources.
""",
    tools=[
        search_knowledge,
        find_entities,
        create_entity,
        update_entity,
        get_entity,
        create_relation,
        record_observation,
        score_entity,
        query_data_source,
        qualify_lead,
        draft_outreach,
        update_pipeline_stage,
        get_pipeline_summary,
        generate_proposal,
        schedule_followup,
    ],
)
```

**Step 2: Commit**

```bash
git add apps/adk-server/servicetsunami_supervisor/sales_agent.py
git commit -m "feat: add sales_agent ADK sub-agent

Full sales automation: BANT qualification, outreach drafting,
pipeline management, proposal generation, follow-up scheduling.
Reuses knowledge graph and connector tools."
```

---

### Task 6: Wire agents into supervisor

**Files:**
- Modify: `apps/adk-server/servicetsunami_supervisor/agent.py`
- Modify: `apps/adk-server/servicetsunami_supervisor/__init__.py`

**Step 1: Update agent.py**

Add imports for the two new sub-agents (after line 11):

```python
from .customer_support import customer_support
from .sales_agent import sales_agent
```

Update the supervisor instruction to add routing rules for the new agents. Add these lines inside the instruction string, after the web_researcher description (after line 27):

```
- customer_support: For customer inquiries, FAQ, product questions, order status, complaints, greetings, and general conversation. This is the DEFAULT for casual or conversational messages.
- sales_agent: For lead qualification, outreach drafting, pipeline management, proposals, and sales automation
```

Add routing guidelines (after line 43):

```
- Customer inquiries, FAQ, product info, order status, complaints -> transfer to customer_support
- Greetings, casual conversation, general chat -> transfer to customer_support
- Lead qualification, BANT analysis, outreach drafting -> transfer to sales_agent
- Pipeline management, stage updates, pipeline summary -> transfer to sales_agent
- Proposal generation, sales automation -> transfer to sales_agent
- If unclear whether support or sales, default to customer_support
```

Update sub_agents list (line 55) to include the new agents:

```python
    sub_agents=[data_analyst, report_generator, knowledge_manager, web_researcher, customer_support, sales_agent],
```

**Step 2: Update __init__.py**

Add imports and exports for the new agents:

```python
from .customer_support import customer_support
from .sales_agent import sales_agent
```

Add to `__all__`:

```python
__all__ = [
    "root_agent",
    "data_analyst",
    "report_generator",
    "knowledge_manager",
    "customer_support",
    "sales_agent",
]
```

**Step 3: Commit**

```bash
git add apps/adk-server/servicetsunami_supervisor/agent.py apps/adk-server/servicetsunami_supervisor/__init__.py
git commit -m "feat: wire customer_support and sales_agent into supervisor

Add routing rules for customer inquiries, general conversation,
lead qualification, pipeline management, and sales automation.
customer_support is the default for casual/conversational messages."
```

---

### Task 7: Create FollowUpWorkflow

**Files:**
- Create: `apps/api/app/workflows/follow_up.py`
- Create: `apps/api/app/workflows/activities/follow_up.py`
- Modify: `apps/api/app/workers/orchestration_worker.py`

**Step 1: Write the workflow**

`apps/api/app/workflows/follow_up.py`:

```python
"""
Temporal workflow for scheduled sales follow-up actions.

Waits for a configurable delay then executes a follow-up action
(send message, update pipeline stage, or create reminder).
"""
from temporalio import workflow
from datetime import timedelta
from dataclasses import dataclass
from typing import Optional


@dataclass
class FollowUpInput:
    entity_id: str
    tenant_id: str
    action: str  # "send_whatsapp", "update_stage", "remind"
    delay_hours: int
    message: str = ""


@workflow.defn(sandboxed=False)
class FollowUpWorkflow:
    """Delayed follow-up action for sales pipeline."""

    @workflow.run
    async def run(self, input: FollowUpInput) -> dict:
        workflow.logger.info(
            f"FollowUp scheduled: {input.action} for entity {input.entity_id} "
            f"in {input.delay_hours}h"
        )

        # Wait for the scheduled delay
        await workflow.sleep(timedelta(hours=input.delay_hours))

        # Execute the follow-up action
        result = await workflow.execute_activity(
            "execute_followup_action",
            args=[input],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=workflow.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
        )

        return result
```

**Step 2: Write the activity**

`apps/api/app/workflows/activities/follow_up.py`:

```python
"""Activities for follow-up workflow."""
import logging
from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn
async def execute_followup_action(input) -> dict:
    """Execute a scheduled follow-up action.

    Supported actions:
    - send_whatsapp: Send a WhatsApp message to the entity's contact
    - update_stage: Update the entity's pipeline stage
    - remind: Log a reminder observation
    """
    from app.db.session import SessionLocal
    from app.models.knowledge_entity import KnowledgeEntity

    action = input.action
    entity_id = input.entity_id
    tenant_id = input.tenant_id
    message = input.message

    logger.info(f"Executing follow-up: {action} for entity {entity_id}")

    db = SessionLocal()
    try:
        entity = db.query(KnowledgeEntity).filter(
            KnowledgeEntity.id == entity_id,
        ).first()

        if not entity:
            return {"status": "error", "error": f"Entity {entity_id} not found"}

        if action == "send_whatsapp":
            # Get phone from entity properties
            phone = (entity.properties or {}).get("phone")
            if not phone:
                return {"status": "error", "error": "No phone number on entity"}

            from app.services.whatsapp_service import whatsapp_service
            result = await whatsapp_service.send_message(
                tenant_id=tenant_id,
                to=phone,
                message=message or f"Following up regarding {entity.name}",
            )
            return {"status": "sent", "action": action, **result}

        elif action == "update_stage":
            props = entity.properties or {}
            old_stage = props.get("pipeline_stage", "none")
            props["pipeline_stage"] = message  # message contains the stage name
            entity.properties = props
            db.commit()
            return {
                "status": "updated",
                "action": action,
                "previous_stage": old_stage,
                "new_stage": message,
            }

        elif action == "remind":
            # Log as observation
            from app.models.knowledge_entity import KnowledgeObservation
            import uuid
            obs = KnowledgeObservation(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(tenant_id),
                observation_text=f"Follow-up reminder: {message or entity.name}",
                observation_type="follow_up_reminder",
                source_type="temporal_workflow",
            )
            db.add(obs)
            db.commit()
            return {"status": "reminded", "action": action, "entity_name": entity.name}

        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception(f"Follow-up action failed: {e}")
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
```

**Step 3: Register in orchestration worker**

In `apps/api/app/workers/orchestration_worker.py`, add imports (after line 23):

```python
from app.workflows.follow_up import FollowUpWorkflow
from app.workflows.activities.follow_up import execute_followup_action
```

Add `FollowUpWorkflow` to the workflows list (after line 53):

```python
            FollowUpWorkflow,
```

Add `execute_followup_action` to the activities list (after line 63):

```python
            execute_followup_action,
```

**Step 4: Commit**

```bash
git add apps/api/app/workflows/follow_up.py apps/api/app/workflows/activities/follow_up.py apps/api/app/workers/orchestration_worker.py
git commit -m "feat: add FollowUpWorkflow for scheduled sales actions

Temporal workflow with configurable delay. Supports send_whatsapp,
update_stage, and remind actions. Registered on orchestration queue."
```

---

### Task 8: Update wizard templates

Update the frontend wizard templates so customer_support and sales_assistant have real tools.

**Files:**
- Modify: `apps/web/src/components/wizard/TemplateSelector.js`

**Step 1: Update customer_support template (lines 6-19)**

Replace the customer_support template config:

```javascript
  {
    id: 'customer_support',
    name: 'Customer Support Agent',
    icon: Headset,
    description: 'Handles customer inquiries, FAQ, order lookups, and general conversation via WhatsApp and chat',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.5,
      max_tokens: 1500,
      system_prompt: 'You are a helpful customer support agent. Answer questions from the knowledge base, look up orders and customer records from connected data sources, and handle complaints with empathy. Escalate when you cannot resolve an issue.',
      tools: ['knowledge_search', 'entity_extraction'],
      suggestDatasets: false,
    },
  },
```

**Step 2: Update sales_assistant template (lines 36-49)**

Replace the sales_assistant template config:

```javascript
  {
    id: 'sales_assistant',
    name: 'Sales Assistant',
    icon: Briefcase,
    description: 'Full sales automation: lead qualification, outreach drafting, pipeline management, and proposal generation',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.6,
      max_tokens: 2000,
      system_prompt: 'You are a sales automation specialist. Qualify leads using BANT, draft personalized outreach, manage the sales pipeline, and generate proposals. Always back recommendations with data from the knowledge graph and connected data sources.',
      tools: ['entity_extraction', 'knowledge_search', 'lead_scoring', 'calculator'],
      scoring_rubric: 'ai_lead',
      suggestDatasets: false,
    },
  },
```

**Step 3: Commit**

```bash
git add apps/web/src/components/wizard/TemplateSelector.js
git commit -m "feat: update wizard templates for customer support and sales agents

Customer support now includes knowledge_search and entity_extraction.
Sales assistant adds lead_scoring and scoring_rubric configuration."
```

---

### Task 9: Deploy and verify

**Step 1: Push to main**

```bash
git push origin main
```

This triggers the CI/CD workflows for api, web, and adk-server.

**Step 2: Trigger ADK deploy**

The ADK server has a separate deploy workflow:

```bash
gh workflow run adk-deploy.yaml -f deploy=true -f environment=prod
```

**Step 3: Verify ADK agents loaded**

Once the ADK pod is running, check that the new agents are loaded:

```bash
kubectl logs -n prod deployment/servicetsunami-adk --tail=50
```

Look for: supervisor loading with 6 sub-agents (previously 4).

**Step 4: Test via WhatsApp**

Send test messages:
1. "Hello" → should route to customer_support, get a friendly response
2. "What products do you offer?" → customer_support, searches knowledge graph
3. "Qualify the lead Acme Corp" → sales_agent, runs BANT qualification
4. Message to a friend → bot should NOT respond (self-message fix)

**Step 5: Test via chat UI**

Create a new chat session with the customer_support or sales_assistant template and verify the tools work.
