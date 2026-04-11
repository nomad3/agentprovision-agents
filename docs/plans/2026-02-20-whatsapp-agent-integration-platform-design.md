# WhatsApp Agent Integration Platform Design

**Goal:** Enable external applications (ai-marketing-platform, PharmApp, future SaaS products) to create AI agents on AgentProvision and expose them to end-users via WhatsApp, using the OpenClaw WhatsApp skill as the messaging bridge. External apps integrate through a REST API — they don't need to manage agent infrastructure, LLM providers, or WhatsApp Business API complexity.

**Architecture:** AgentProvision becomes an "Agents-as-a-Service" backend. External apps register as integration partners, provision agents with specific skills and rubrics, and connect them to WhatsApp phone numbers. Inbound WhatsApp messages route through a webhook handler to the correct tenant's agent, which processes them using the knowledge graph, scoring rubrics, and configured skills, then responds back through WhatsApp.

**Tech Stack:** FastAPI (webhook receiver + partner API), OpenClaw (WhatsApp Business API bridge), Temporal (async message processing), Meta Cloud API (WhatsApp), existing SkillRouter + CredentialVault

---

## System Architecture

```
                        ┌──────────────────────────────────────────┐
                        │        External Applications             │
                        │                                          │
                        │  ┌─────────────┐  ┌─────────────────┐   │
                        │  │ ai-marketing │  │    PharmApp      │   │
                        │  │  platform    │  │  (marketplace)   │   │
                        │  └──────┬───────┘  └───────┬─────────┘   │
                        │         │                  │              │
                        └─────────┼──────────────────┼──────────────┘
                                  │  Partner API     │
                                  │  (API key auth)  │
                                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     AgentProvision Platform                         │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Partner API   │  │ Webhook      │  │ Agent Orchestration      │  │
│  │ /api/v1/      │  │ Handler      │  │                          │  │
│  │ partners/     │  │ /webhooks/   │  │  Supervisor → knowledge  │  │
│  │               │  │ whatsapp/    │  │  manager → scorer →      │  │
│  │ - agents      │  │ {tenant}     │  │  web_researcher          │  │
│  │ - messages    │  │              │  │                          │  │
│  │ - scoring     │  └──────┬───────┘  └────────────┬─────────────┘  │
│  │ - skills      │         │                       │                │
│  └──────┬────────┘         │                       │                │
│         │                  ▼                       ▼                │
│         │         ┌──────────────────────────────────────┐         │
│         │         │        SkillRouter                    │         │
│         │         │  resolve instance → decrypt creds →   │         │
│         │         │  call OpenClaw → log trace            │         │
│         └────────►│                                       │         │
│                   └──────────────────┬───────────────────┘         │
│                                      │                              │
│                   ┌──────────────────▼───────────────────┐         │
│                   │     OpenClaw Instance (per tenant)    │         │
│                   │                                       │         │
│                   │  WhatsApp skill ←→ Meta Cloud API     │         │
│                   │  Slack skill, Gmail skill, etc.       │         │
│                   └──────────────────┬───────────────────┘         │
│                                      │                              │
└──────────────────────────────────────┼──────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │  WhatsApp Users  │
                              │  (end customers) │
                              └─────────────────┘
```

---

## Core Concepts

### Integration Partner

An external application that consumes AgentProvision's agent infrastructure. Each partner:
- Gets a dedicated tenant (multi-tenant isolation)
- Authenticates with an API key (not JWT — long-lived, server-to-server)
- Can create agents, configure skills, store credentials, trigger actions
- Receives webhook callbacks for inbound messages and agent events

### WhatsApp-Connected Agent

An agent configured with the WhatsApp skill that can:
- **Receive** inbound messages via Meta webhook → agent processing → auto-reply
- **Send** outbound messages triggered by the partner's API calls
- **Score** entities mentioned in conversations using configurable rubrics
- **Extract** entities from conversations into the knowledge graph
- **Execute** multi-step workflows (research → score → respond)

### Message Flow Types

| Flow | Trigger | Path |
|---|---|---|
| **Inbound** | End-user sends WhatsApp message | Meta webhook → ST webhook handler → agent → knowledge extraction → response → WhatsApp reply |
| **Outbound** | Partner API triggers a message | Partner API → SkillRouter → OpenClaw → WhatsApp Business API → end-user |
| **Agent-initiated** | Agent decides to follow up | Temporal scheduler → agent evaluation → SkillRouter → WhatsApp |

---

## Data Model

### New: `integration_partners` table

```sql
CREATE TABLE integration_partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,              -- "ai-marketing-platform"
    api_key_hash VARCHAR(255) NOT NULL,      -- bcrypt hash of partner API key
    api_key_prefix VARCHAR(8) NOT NULL,      -- first 8 chars for identification
    webhook_url VARCHAR(500),                -- partner's callback URL for events
    webhook_secret VARCHAR(255),             -- HMAC secret for signing callbacks
    allowed_skills TEXT[] DEFAULT '{}',      -- ["whatsapp", "slack", "gmail"]
    rate_limit_per_minute INT DEFAULT 60,
    status VARCHAR(20) DEFAULT 'active',     -- active, suspended, revoked
    metadata JSONB DEFAULT '{}',             -- partner-specific config
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### New: `whatsapp_connections` table

```sql
CREATE TABLE whatsapp_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    agent_id UUID NOT NULL REFERENCES agents(id),
    phone_number_id VARCHAR(50) NOT NULL,    -- Meta WhatsApp phone number ID
    display_phone VARCHAR(20),               -- +1-555-0100
    waba_id VARCHAR(50),                     -- WhatsApp Business Account ID
    verify_token VARCHAR(100) NOT NULL,      -- webhook verification token
    status VARCHAR(20) DEFAULT 'pending',    -- pending, verified, active, disconnected
    auto_reply BOOLEAN DEFAULT TRUE,         -- agent auto-responds to inbound
    greeting_message TEXT,                    -- first-time contact greeting
    business_hours JSONB,                    -- {"mon": {"start": "09:00", "end": "17:00"}, ...}
    away_message TEXT,                       -- outside business hours reply
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New: `message_log` table

```sql
CREATE TABLE message_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    agent_id UUID REFERENCES agents(id),
    whatsapp_connection_id UUID REFERENCES whatsapp_connections(id),
    direction VARCHAR(10) NOT NULL,          -- inbound, outbound
    wa_message_id VARCHAR(100),              -- Meta's message ID
    from_number VARCHAR(20),
    to_number VARCHAR(20),
    message_type VARCHAR(20),                -- text, image, document, template, interactive
    content TEXT,
    media_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'received',   -- received, processing, replied, sent, delivered, read, failed
    agent_response TEXT,                     -- what the agent replied
    entities_extracted UUID[],               -- entity IDs extracted from this message
    score_triggered BOOLEAN DEFAULT FALSE,
    processing_time_ms INT,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Partner API Endpoints

All under `/api/v1/partners/`, authenticated with `X-API-Key` header.

### Partner Management

| Method | Path | Description |
|---|---|---|
| `POST /partners/register` | Register a new integration partner (creates tenant + API key) |
| `POST /partners/api-keys/rotate` | Rotate API key |
| `GET /partners/usage` | Usage stats (messages sent, entities scored, API calls) |

### Agent Management

| Method | Path | Description |
|---|---|---|
| `POST /partners/agents` | Create an agent with skills and rubric |
| `GET /partners/agents` | List partner's agents |
| `PUT /partners/agents/{id}` | Update agent config |
| `DELETE /partners/agents/{id}` | Deactivate agent |

### WhatsApp Connection

| Method | Path | Description |
|---|---|---|
| `POST /partners/whatsapp/connect` | Connect a WhatsApp phone number to an agent |
| `GET /partners/whatsapp/connections` | List connections |
| `PUT /partners/whatsapp/connections/{id}` | Update (greeting, business hours, auto-reply) |
| `DELETE /partners/whatsapp/connections/{id}` | Disconnect |

### Messaging

| Method | Path | Description |
|---|---|---|
| `POST /partners/messages/send` | Send outbound WhatsApp message |
| `POST /partners/messages/send-template` | Send a WhatsApp template message (for initiating conversations) |
| `GET /partners/messages/{agent_id}` | Get message history for an agent |
| `GET /partners/messages/{agent_id}/conversations` | Get conversation threads grouped by phone number |

### Knowledge & Scoring

| Method | Path | Description |
|---|---|---|
| `POST /partners/entities` | Create an entity in the knowledge graph |
| `POST /partners/entities/{id}/score` | Score entity with rubric |
| `GET /partners/entities` | Search entities |
| `POST /partners/entities/batch-score` | Batch score multiple entities |

### Skills Execution

| Method | Path | Description |
|---|---|---|
| `POST /partners/skills/execute` | Execute any configured skill directly (bypasses agent) |
| `GET /partners/skills` | List available skills for this partner |

---

## WhatsApp Webhook Handler

### Meta Webhook Verification

```
GET /webhooks/whatsapp/{tenant_short_id}
  ?hub.mode=subscribe
  &hub.verify_token={verify_token}
  &hub.challenge={challenge}

→ Returns hub.challenge if verify_token matches
```

### Inbound Message Processing

```
POST /webhooks/whatsapp/{tenant_short_id}

Body: Meta webhook payload (message, status update, etc.)
```

**Processing flow:**

```
1. Parse Meta webhook payload
   → Extract: from_number, message_text, message_type, wa_message_id

2. Resolve tenant + agent
   → Lookup whatsapp_connections WHERE tenant_short_id AND phone_number_id
   → Get associated agent_id

3. Check business hours (if configured)
   → Outside hours → send away_message via OpenClaw, log, return
   → First-time contact → send greeting_message first

4. Log inbound message
   → Insert into message_log (direction=inbound)

5. Start Temporal workflow: WhatsAppMessageWorkflow
   → Activity 1: Extract entities from message text (entity_extraction tool)
   → Activity 2: Search knowledge graph for context (knowledge_search)
   → Activity 3: Generate agent response (ADK agent with conversation context)
   → Activity 4: Score any new/updated entities if relevant
   → Activity 5: Send reply via OpenClaw WhatsApp skill
   → Activity 6: Log outbound message + update message_log status

6. Return 200 to Meta (must respond within 5 seconds)
   → Actual processing is async via Temporal
```

### Status Updates

Meta sends delivery status updates (sent → delivered → read). Update `message_log.status` accordingly.

---

## Use Case: ai-marketing-platform

### Integration Flow

```
1. Register as partner
   POST /api/v1/partners/register
   {
     "name": "ai-marketing-platform",
     "webhook_url": "https://ai-marketing.example.com/webhooks/st"
   }
   → Returns: { api_key: "st_partner_...", tenant_id: "..." }

2. Create a Marketing Intelligence agent
   POST /api/v1/partners/agents
   {
     "name": "Marketing Outreach Agent",
     "template": "marketing_intelligence",
     "scoring_rubric": "marketing_signal",
     "tools": ["entity_extraction", "knowledge_search", "lead_scoring"],
     "system_prompt": "You are a marketing engagement specialist for [brand]. Score leads based on their interaction history and respond with personalized offers."
   }

3. Connect WhatsApp number
   POST /api/v1/partners/whatsapp/connect
   {
     "agent_id": "<agent-uuid>",
     "phone_number_id": "123456789",
     "waba_id": "987654321",
     "credentials": {
       "api_key": "<meta-whatsapp-api-key>"
     },
     "auto_reply": true,
     "greeting_message": "Hi! I'm the AI marketing assistant for [brand]. How can I help you today?"
   }

4. Send outbound campaign message
   POST /api/v1/partners/messages/send-template
   {
     "agent_id": "<agent-uuid>",
     "to": "+1234567890",
     "template_name": "marketing_offer_v2",
     "template_params": ["John", "25% off", "Feb 28"]
   }

5. Inbound reply arrives → agent processes → auto-responds
   → Entity extracted: "John, interested in premium plan"
   → Scored with marketing_signal rubric: 78
   → Agent responds: "Great choice, John! Here's what the Premium plan includes..."

6. Partner checks engagement scores
   GET /api/v1/partners/entities?category=lead&min_score=70
   → Returns high-engagement leads for campaign targeting
```

### Webhook Callbacks to Partner

AgentProvision sends events back to the partner's webhook URL:

```json
{
  "event": "message.inbound",
  "agent_id": "<uuid>",
  "from": "+1234567890",
  "message": "I'm interested in the premium plan",
  "entities_extracted": [
    {"name": "John", "category": "contact", "score": 78}
  ],
  "agent_response": "Great choice, John! Here's what the Premium plan includes...",
  "timestamp": "2026-02-20T18:30:00Z"
}
```

Event types: `message.inbound`, `message.delivered`, `message.read`, `entity.scored`, `agent.error`

---

## Use Case: PharmApp (Medicine Marketplace)

### Integration Flow

```
1. Register as partner
   POST /api/v1/partners/register
   { "name": "pharmapp-marketplace" }

2. Create a Pharmacy Support agent
   POST /api/v1/partners/agents
   {
     "name": "PharmApp Assistant",
     "tools": ["entity_extraction", "knowledge_search"],
     "system_prompt": "You are a pharmacy assistant for PharmApp. Help customers find medicines, check availability, and track orders. Never provide medical advice — always recommend consulting a healthcare professional."
   }

3. Connect WhatsApp for customer support
   POST /api/v1/partners/whatsapp/connect
   {
     "agent_id": "<agent-uuid>",
     "phone_number_id": "555000123",
     "auto_reply": true,
     "greeting_message": "Welcome to PharmApp! I can help you find medicines, check order status, or answer questions. How can I help?",
     "business_hours": {
       "mon": {"start": "08:00", "end": "22:00"},
       "tue": {"start": "08:00", "end": "22:00"},
       "sat": {"start": "10:00", "end": "18:00"}
     },
     "away_message": "We're currently closed. Our hours are Mon-Fri 8am-10pm, Sat 10am-6pm. We'll respond when we're back!"
   }

4. Customer sends WhatsApp message: "Do you have ibuprofen 400mg?"
   → Agent searches knowledge graph for product entities
   → Responds with availability + pricing
   → Extracts entity: {"name": "Ibuprofen 400mg", "category": "product", "entity_type": "medicine"}

5. PharmApp gets webhook callback with extracted intent
   → PharmApp backend checks real-time inventory
   → Triggers follow-up via API:
     POST /api/v1/partners/messages/send
     { "to": "+1234567890", "text": "Ibuprofen 400mg is in stock at 3 pharmacies near you. Tap to order: [link]" }
```

---

## Authentication: Partner API Keys

### Key Format
```
st_partner_live_<32-char-random>    (production)
st_partner_test_<32-char-random>    (sandbox)
```

### Auth Flow
```
Request:
  X-API-Key: st_partner_live_abc123...

Server:
  1. Extract prefix (first 8 chars after "st_partner_live_")
  2. Lookup integration_partners WHERE api_key_prefix = prefix AND status = 'active'
  3. bcrypt.verify(provided_key, stored_hash)
  4. Set request.state.tenant_id = partner.tenant_id
  5. Check rate limit (partner.rate_limit_per_minute)
  6. Check skill allowlist (partner.allowed_skills)
```

### Rate Limiting

Per-partner rate limits tracked in Redis:
- Default: 60 requests/minute
- Burst: 10 requests/second
- WhatsApp-specific: Meta enforces 1000 business-initiated messages/day (free tier)

---

## Temporal Workflows

### WhatsAppMessageWorkflow

Processes inbound WhatsApp messages asynchronously.

```
Queue: agentprovision-whatsapp
Timeout: 30 seconds

Activities:
  1. extract_entities(message_text, tenant_id)
     → Returns list of extracted entities
  2. search_context(entities, tenant_id)
     → Returns relevant knowledge graph context
  3. generate_response(message, context, agent_config)
     → ADK agent generates reply
  4. score_entities(entity_ids, rubric_id, tenant_id)
     → Score any newly created/updated entities
  5. send_whatsapp_reply(connection_id, to_number, response_text)
     → SkillRouter → OpenClaw → Meta API
  6. notify_partner(partner_webhook_url, event_payload)
     → POST to partner's webhook URL with HMAC signature
```

### WhatsAppCampaignWorkflow

Processes batch outbound messages (e.g., marketing campaigns).

```
Queue: agentprovision-whatsapp
Timeout: 5 minutes

Input: { agent_id, template_name, recipients: [{phone, params}], rate_limit_per_second: 10 }

Activities:
  1. validate_template(template_name, waba_id)
  2. for each recipient (rate-limited):
     a. send_template_message(connection_id, phone, template, params)
     b. log_outbound_message(...)
  3. notify_partner(summary: { sent, failed, total })
```

---

## Security Considerations

| Concern | Mitigation |
|---|---|
| WhatsApp credentials at rest | Fernet encryption via CredentialVault (existing) |
| Partner API key exposure | bcrypt hash storage, prefix-only lookup, key rotation endpoint |
| Webhook payload authenticity | HMAC-SHA256 signature on all callbacks to partner |
| Meta webhook verification | Per-connection verify_token checked on GET challenge |
| Message content privacy | Messages stored in tenant-isolated `message_log`, encrypted at rest via Cloud SQL |
| Rate abuse | Per-partner rate limits + Meta's own rate limiting |
| Medical advice liability (PharmApp) | System prompt guardrails + disclaimer in greeting |

---

## Implementation Phases

### Phase 1: Partner API Foundation
- `integration_partners` table + migration
- API key generation, hashing, rotation
- Partner auth middleware (`X-API-Key`)
- `POST /partners/register`, `GET /partners/usage`
- Partner-scoped agent CRUD (`/partners/agents`)

### Phase 2: WhatsApp Connection
- `whatsapp_connections` table + migration
- `POST /partners/whatsapp/connect` — stores credentials via CredentialVault
- Meta webhook verification handler (`GET /webhooks/whatsapp/{tenant}`)
- Wire OpenClaw instance provisioning to actually trigger Temporal (fix existing TODO)

### Phase 3: Inbound Message Processing
- `message_log` table + migration
- Webhook handler (`POST /webhooks/whatsapp/{tenant}`)
- `WhatsAppMessageWorkflow` — entity extraction → context → agent response → reply
- Business hours + greeting message logic

### Phase 4: Outbound Messaging
- `POST /partners/messages/send` — direct text messages
- `POST /partners/messages/send-template` — template messages
- `WhatsAppCampaignWorkflow` — batch sending with rate limiting

### Phase 5: Knowledge & Scoring Integration
- `/partners/entities` CRUD (scoped to partner's tenant)
- `/partners/entities/{id}/score` with rubric selection
- `/partners/entities/batch-score`
- Auto-scoring on entity extraction from WhatsApp messages

### Phase 6: Partner Webhooks
- Webhook callback system (events → partner URL)
- HMAC-SHA256 signature on payloads
- Retry with exponential backoff (3 attempts)
- Event types: message.inbound, message.delivered, entity.scored, agent.error

---

## Files to Create/Modify

### New Files
| File | Description |
|---|---|
| `apps/api/app/models/integration_partner.py` | Partner model |
| `apps/api/app/models/whatsapp_connection.py` | WhatsApp connection model |
| `apps/api/app/models/message_log.py` | Message log model |
| `apps/api/app/schemas/partner.py` | Partner API schemas |
| `apps/api/app/schemas/whatsapp.py` | WhatsApp connection + message schemas |
| `apps/api/app/api/v1/partners.py` | Partner API routes |
| `apps/api/app/api/v1/webhooks.py` | WhatsApp webhook handler |
| `apps/api/app/services/partner_auth.py` | API key auth middleware |
| `apps/api/app/services/whatsapp.py` | WhatsApp connection + messaging service |
| `apps/api/app/workflows/whatsapp_message.py` | Inbound message processing workflow |
| `apps/api/app/workflows/whatsapp_campaign.py` | Batch outbound campaign workflow |
| `apps/api/migrations/034_integration_partners.sql` | Partners table |
| `apps/api/migrations/035_whatsapp_connections.sql` | WhatsApp + message_log tables |

### Modified Files
| File | Change |
|---|---|
| `apps/api/app/api/v1/routes.py` | Mount `/partners` and `/webhooks` routers |
| `apps/api/app/models/__init__.py` | Register new models |
| `apps/api/app/workers/orchestration_worker.py` | Register WhatsApp workflows + activities |
| `apps/api/app/workflows/openclaw_provision.py` | Wire Temporal trigger from API (fix TODO) |
