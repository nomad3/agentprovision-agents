# PharmApp ↔ AgentProvision WhatsApp Integration Design

**Goal:** Connect AgentProvision's AI agents to PharmApp (Remedia), a Chilean medication marketplace, enabling WhatsApp-based customer engagement for medication search, ordering, and retention.

**Architecture:** PharmApp handles domain logic (medication search, orders, payments). AgentProvision handles AI orchestration (conversational agents, knowledge graph, WhatsApp channel). Communication flows bidirectionally: PharmApp creates WhatsApp tasks for outbound messages, AgentProvision agents handle inbound conversational AI with PharmApp domain knowledge.

## Integration Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     PharmApp (Remedia)                     │
│  FastAPI · PostgreSQL/PostGIS · 11K meds · 2.7K pharmacies │
│                                                            │
│  Outbound: send_otp, order_confirmation, price_alert,     │
│            refill_reminder, delivery_update                │
│  Inbound:  medication search, order status (local handler) │
│            → fallback to AgentProvision chat for AI        │
└────────────────────────┬─────────────────────────────────┘
                         │ POST /api/v1/tasks (task_type=whatsapp)
                         │ POST /api/v1/chat/sessions/.../messages
                         ▼
┌──────────────────────────────────────────────────────────┐
│                   AgentProvision API                      │
│                                                            │
│  Task Handler: auto-execute WhatsApp tasks on creation    │
│  Chat Service: route messages through ADK supervisor       │
│  WhatsApp Service: neonize (direct WhatsApp Web)          │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────┐
│                   ADK Supervisor                          │
│                                                            │
│  customer_support: medication FAQ, order help, Spanish    │
│  sales_agent: pharmacy partnerships, B2B outreach,        │
│               retention campaigns, PharmApp funnel         │
└──────────────────────────────────────────────────────────┘
```

## Changes

### 1. WhatsApp Task Auto-Execution (API)

**File:** `apps/api/app/api/v1/agent_tasks.py`

When PharmApp creates a task with `task_type="whatsapp"` and `context.skill="whatsapp"`:
- Extract payload (action, recipient_phone, message_body)
- Send via `whatsapp_service.send_message()` immediately
- Update task status to "completed" with message_id in output
- On error: set status "failed" with error message

This avoids the full TaskExecutionWorkflow (dispatch→recall→execute→persist→evaluate) which is overkill for a simple WhatsApp send.

### 2. PharmApp-Aware Sales Agent (ADK)

**File:** `apps/adk-server/agentprovision_supervisor/sales_agent.py`

Add PharmApp domain context to the sales agent instruction:
- Medication marketplace for Chile (Remedia brand)
- B2B: pharmacy chain partnerships, onboarding, listings
- B2C: customer retention via refill reminders, price alerts, loyalty tiers
- WhatsApp as primary sales channel
- Spanish language support
- Data source query patterns for PharmApp's schema

### 3. PharmApp-Aware Customer Support (ADK)

**File:** `apps/adk-server/agentprovision_supervisor/customer_support.py`

Add PharmApp context for inbound WhatsApp conversations:
- Medication FAQ (dosage, interactions, availability)
- Price comparison across pharmacies
- Order status and tracking
- Pharmacy information (hours, location)
- Spanish as primary language
- Empathetic, accessible tone for healthcare context

### 4. Updated Supervisor Routing (ADK)

**File:** `apps/adk-server/agentprovision_supervisor/agent.py`

Add PharmApp-specific routing:
- Medication queries, order help, pharmacy info → customer_support
- Pharmacy partnerships, retention campaigns → sales_agent
- Spanish language queries → appropriate agent based on intent

## PharmApp Data Source Schema (for agent SQL queries)

```sql
-- Key tables agents can query via query_data_source:
medications (id, name, active_ingredient, dosage, form, lab, requires_prescription)
pharmacies (id, chain, name, address, comuna, phone, hours, is_retail)
prices (id, medication_id, pharmacy_id, price, in_stock, scraped_at)
orders (id, user_id, pharmacy_id, status, payment_provider, total, created_at)
order_items (id, order_id, medication_id, price_id, quantity, subtotal)
users (id, phone_number, name, comuna, role)
```

## Flow: PharmApp Outbound WhatsApp

1. PharmApp event (OTP, order, payment, price alert, refill)
2. PharmApp's WhatsApp service calls `agentprovision_client.send_whatsapp(phone, message)`
3. AgentProvision `POST /api/v1/tasks` creates task with `task_type="whatsapp"`
4. Auto-execution: `whatsapp_service.send_message()` sends via neonize
5. Task updated to "completed" with message_id

## Flow: Inbound WhatsApp → AI Response

1. Customer sends WhatsApp message
2. Neonize receives → routes to ADK supervisor via chat service
3. Supervisor routes to customer_support (default) or sales_agent
4. Agent uses query_data_source for PharmApp data (if connected)
5. Agent generates Spanish-language response
6. Response sent back via WhatsApp
