# Dynamic Workflows — Visual Builder + Natural Language + Template Marketplace

> Users create, edit, and share automated workflows through a visual builder, natural language commands, or pre-built templates. Each workflow step can call MCP tools, invoke agents, apply conditions, wait for events, or trigger other workflows.

**Date:** 2026-03-21
**Status:** Design

---

## 1. Problem

Today's 17 workflows are hardcoded Python classes. Adding a new workflow requires:
- Writing a Temporal workflow + activities in Python
- Registering in a worker
- Deploying the API
- No UI for non-developers

Users should be able to create workflows like:
> "Every morning at 8am, scan my inbox, extract new contacts into the knowledge graph, score them with the AI lead rubric, and send me a summary on WhatsApp."

---

## 2. Architecture

### 2.1 Workflow Definition (JSON Schema)

A dynamic workflow is a JSON document stored in the database, not a Python class.

```json
{
  "id": "wf_inbox_to_leads",
  "name": "Inbox → Lead Pipeline",
  "description": "Scan inbox, extract contacts, score leads, notify",
  "version": 1,
  "trigger": {
    "type": "cron",
    "schedule": "0 8 * * *",
    "timezone": "America/Santiago"
  },
  "steps": [
    {
      "id": "scan_inbox",
      "type": "mcp_tool",
      "tool": "search_emails",
      "params": {"query": "is:unread newer_than:1d", "max_results": 20},
      "output": "emails"
    },
    {
      "id": "extract_contacts",
      "type": "agent",
      "agent": "luna",
      "prompt": "Extract all people and companies from these emails. Create knowledge entities for each new contact: {{emails}}",
      "output": "contacts"
    },
    {
      "id": "score_leads",
      "type": "for_each",
      "collection": "{{contacts}}",
      "as": "contact",
      "steps": [
        {
          "id": "score",
          "type": "mcp_tool",
          "tool": "score_entity",
          "params": {"entity_id": "{{contact.id}}", "rubric": "ai_lead"},
          "output": "score"
        },
        {
          "id": "filter_hot",
          "type": "condition",
          "if": "{{score.score}} >= 70",
          "then": "notify",
          "else": "skip"
        },
        {
          "id": "notify",
          "type": "mcp_tool",
          "tool": "send_email",
          "params": {
            "to": "{{tenant.email}}",
            "subject": "Hot lead: {{contact.name}} ({{score.score}}/100)",
            "body": "{{score.reasoning}}"
          }
        }
      ]
    },
    {
      "id": "summary",
      "type": "agent",
      "agent": "luna",
      "prompt": "Summarize today's inbox scan: {{contacts.length}} contacts found, {{hot_leads.length}} hot leads. Send via WhatsApp.",
      "output": "summary"
    }
  ]
}
```

### 2.2 Step Types

| Type | Description | Example |
|------|-------------|---------|
| `mcp_tool` | Call any of the 81+ MCP tools | search_emails, create_entity, score_entity |
| `agent` | Send a prompt to an agent (Luna, Code, etc.) | "Analyze this data and..." |
| `condition` | Branch based on expression | if score >= 70 then notify |
| `for_each` | Loop over a collection | for each email in inbox |
| `wait` | Pause for duration or event | wait 5 minutes, wait for webhook |
| `parallel` | Run steps concurrently | scan inbox AND check calendar |
| `webhook_trigger` | Wait for external webhook | Stripe payment received |
| `workflow` | Call another workflow | run "score_lead" sub-workflow |
| `transform` | Map/filter/reduce data | extract names from JSON |
| `human_approval` | Pause until user approves | "Send this email? [approve/reject]" |

### 2.3 Trigger Types

| Trigger | Description | Example |
|---------|-------------|---------|
| `cron` | Scheduled (cron expression) | "0 8 * * *" (daily 8am) |
| `interval` | Every N minutes/hours | every 15 minutes |
| `webhook` | External HTTP trigger | Stripe, GitHub, Jira webhook |
| `event` | Internal platform event | entity_created, email_received, chat_message |
| `manual` | User clicks "Run" in UI | one-click execution |
| `agent` | Luna creates/triggers it | "run my inbox pipeline" |

### 2.4 Data Model

```sql
CREATE TABLE dynamic_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    definition JSONB NOT NULL,  -- The full workflow JSON
    version INT NOT NULL DEFAULT 1,
    status VARCHAR(20) DEFAULT 'draft',  -- draft, active, paused, archived
    trigger_config JSONB,  -- Trigger settings (cron, webhook, event)
    created_by UUID REFERENCES users(id),
    tags TEXT[],
    -- Marketplace fields
    tier VARCHAR(20) DEFAULT 'custom',  -- native, community, custom
    source_template_id UUID,  -- If cloned from a template
    public BOOLEAN DEFAULT false,
    installs INT DEFAULT 0,
    rating FLOAT,
    -- Execution stats
    run_count INT DEFAULT 0,
    last_run_at TIMESTAMP,
    avg_duration_ms INT,
    success_rate FLOAT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    workflow_id UUID NOT NULL REFERENCES dynamic_workflows(id),
    trigger_type VARCHAR(20),
    status VARCHAR(20) DEFAULT 'running',  -- running, completed, failed, cancelled
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_ms INT,
    step_results JSONB,  -- Results from each step
    error TEXT,
    input_data JSONB,  -- Trigger input (webhook payload, etc.)
    output_data JSONB  -- Final workflow output
);

CREATE TABLE workflow_step_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs(id),
    step_id VARCHAR(100) NOT NULL,
    step_type VARCHAR(50),
    status VARCHAR(20),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INT,
    input_data JSONB,
    output_data JSONB,
    error TEXT,
    tokens_used INT,
    cost_usd FLOAT
);
```

---

## 3. Execution Engine

### 3.1 How It Works

The workflow executor is a single Temporal workflow that interprets the JSON definition at runtime. No code generation needed.

```python
@workflow.defn
class DynamicWorkflowExecutor:
    """Execute any workflow from its JSON definition."""

    @workflow.run
    async def run(self, workflow_def: dict, input_data: dict) -> dict:
        context = {"input": input_data}

        for step in workflow_def["steps"]:
            result = await workflow.execute_activity(
                execute_step,
                args=[step, context],
                start_to_close_timeout=timedelta(minutes=10),
            )
            context[step["id"]] = result

            # Handle conditions
            if step["type"] == "condition" and not result["passed"]:
                if step.get("else") == "skip":
                    continue

        return context
```

### 3.2 Step Executor Activity

Each step type has a handler:

```python
@activity.defn
async def execute_step(step: dict, context: dict) -> dict:
    step_type = step["type"]

    if step_type == "mcp_tool":
        return await call_mcp_tool(step["tool"], resolve_params(step["params"], context))

    elif step_type == "agent":
        return await call_agent(step["agent"], resolve_template(step["prompt"], context))

    elif step_type == "condition":
        return {"passed": evaluate_expression(step["if"], context)}

    elif step_type == "for_each":
        collection = resolve_value(step["collection"], context)
        results = []
        for item in collection:
            sub_context = {**context, step["as"]: item}
            for sub_step in step["steps"]:
                sub_result = await execute_step(sub_step, sub_context)
                sub_context[sub_step["id"]] = sub_result
            results.append(sub_context)
        return results

    elif step_type == "wait":
        await asyncio.sleep(parse_duration(step["duration"]))
        return {"waited": step["duration"]}

    elif step_type == "transform":
        return transform_data(step["operation"], context)
```

### 3.3 Template Variables

Steps can reference outputs from previous steps using `{{variable}}` syntax:

```
{{emails}}              → output of the "scan_inbox" step
{{contact.name}}        → property of the current loop item
{{score.score}}         → nested output access
{{contacts.length}}     → collection size
{{tenant.email}}        → tenant context
{{input.webhook_data}}  → trigger input
```

---

## 4. Creation Methods

### 4.1 Visual Builder (UI)

A drag-and-drop canvas where users:
1. Pick a trigger (cron, webhook, manual)
2. Add steps by dragging from a palette (MCP tools, agents, conditions, loops)
3. Connect steps with arrows
4. Configure each step's parameters
5. Test with sample data
6. Activate

**UI Components:**
- `WorkflowCanvas` — main drag-drop area (react-flow or reactflow)
- `StepPalette` — sidebar with available step types
- `StepConfigPanel` — right panel for editing step params
- `TriggerConfig` — trigger type selector + schedule builder
- `RunHistory` — execution logs and step-by-step trace
- `TestRunner` — dry-run with sample input

### 4.2 Natural Language (via Luna)

User tells Luna:
> "Create a workflow that runs every morning: scan my inbox for unread emails, extract contacts, score them as leads, and WhatsApp me a summary of any hot ones."

Luna uses the `create_dynamic_workflow` MCP tool to:
1. Parse the intent into workflow JSON
2. Map actions to MCP tools and step types
3. Set up the trigger (cron for "every morning")
4. Return the workflow for user review
5. Activate on approval

**MCP Tools for Workflow Management:**
- `create_dynamic_workflow` — create from description or JSON
- `list_dynamic_workflows` — list tenant's workflows
- `run_dynamic_workflow` — trigger manual execution
- `get_workflow_run` — check run status and results
- `update_dynamic_workflow` — modify steps or trigger
- `pause_dynamic_workflow` — pause/resume

### 4.3 Template Marketplace

Pre-built workflows that users can install with one click:

**Native Templates (bundled):**

| Template | Trigger | Steps |
|----------|---------|-------|
| Inbox Monitor | Every 15 min | Scan inbox → Extract contacts → Create entities → Notify |
| Daily Briefing | Cron 8am | Check email + calendar + knowledge → Generate summary → WhatsApp |
| Lead Pipeline | Event: entity_created | Score lead → Enrich data → Create Jira ticket → Notify sales |
| Competitor Watch | Daily | Scrape competitor sites → Compare changes → Create observations → Alert |
| Code Review | Webhook: PR opened | Analyze PR → Run tests → Score quality → Post review comment |
| Deal Pipeline | Manual | Discover → Score → Research → Outreach → Follow up |
| Invoice Processor | Email: invoice received | Extract data → Create entity → Update knowledge graph → Notify |
| Weekly Report | Cron Friday 5pm | Query metrics → Generate report → Email stakeholders |

**Community Templates (GitHub import):**
Same mechanism as skill marketplace — import from GitHub repos.

**Custom Templates:**
Users save their workflows as templates to share.

---

## 5. Integration with Existing Systems

### 5.1 MCP Tools (81+)
Every MCP tool is available as a workflow step. The workflow engine calls them via the same internal API.

### 5.2 Agents (Luna, Code, Data, etc.)
Agent steps send a prompt to the CLI orchestrator. The agent has access to all MCP tools during execution.

### 5.3 Knowledge Graph
Workflows can read/write knowledge entities and observations. Each workflow run can auto-extract entities from its outputs.

### 5.4 RL System
Each workflow run is scored:
- Success/failure tracking
- Duration and cost tracking
- User satisfaction (if interactive)
- Feeds into RL for optimizing step execution (which agent handles which step best)

### 5.5 Webhook Connectors
The existing webhook connector system provides inbound triggers for dynamic workflows.

### 5.6 Temporal
Dynamic workflows execute on Temporal for durability. A single `DynamicWorkflowExecutor` workflow class handles all dynamic workflows — no per-workflow code needed.

---

## 6. Frontend Design

### 6.1 Workflows Page (Enhanced)

Current tabs: Executions | Designs

New tabs: **My Workflows** | **Templates** | **Runs** | **Builder**

**My Workflows tab:**
- List of tenant's dynamic workflows with status (active/paused/draft)
- Quick actions: Run, Pause, Edit, Delete
- Stats: run count, success rate, last run

**Templates tab:**
- Browse native + community + custom templates
- One-click install → creates a copy in "My Workflows"
- Search and filter by category

**Runs tab:**
- Real-time execution log (existing, enhanced)
- Step-by-step trace with inputs/outputs per step
- Duration, tokens, cost per step
- Re-run failed workflows

**Builder tab:**
- Visual workflow editor (react-flow canvas)
- Step palette on the left
- Config panel on the right
- Live preview / test runner
- Save as draft or activate

### 6.2 Workflow Builder Components

```
┌──────────────────────────────────────────────────────────────┐
│  [< Back]  Inbox Lead Pipeline  [Draft ▾]  [Test] [Save]    │
├──────────┬───────────────────────────────────┬───────────────┤
│ STEPS    │                                   │ CONFIGURE     │
│          │    ┌─────────┐                    │               │
│ ▸ Trigger│    │  Cron   │                    │ Step: Scan    │
│ ▸ MCP    │    │  8am    │                    │ Tool: search  │
│ ▸ Agent  │    └────┬────┘                    │ _emails       │
│ ▸ Logic  │         │                         │               │
│ ▸ Loop   │    ┌────▼────┐                    │ Params:       │
│ ▸ Wait   │    │  Scan   │ ◄── selected      │ query: is:    │
│ ▸ Webhook│    │  Inbox  │                    │   unread      │
│          │    └────┬────┘                    │ max: 20       │
│          │         │                         │               │
│          │    ┌────▼────┐                    │ Output var:   │
│          │    │ Extract │                    │ emails        │
│          │    │ Contacts│                    │               │
│          │    └────┬────┘                    │               │
│          │         │                         │               │
│          │    ┌────▼────┐                    │               │
│          │    │  Score  │                    │               │
│          │    │ for each│                    │               │
│          │    └────┬────┘                    │               │
│          │    ┌────▼────┐                    │               │
│          │    │ Notify  │                    │               │
│          │    │ WhatsApp│                    │               │
│          │    └─────────┘                    │               │
├──────────┴───────────────────────────────────┴───────────────┤
│  Console: Ready to test. Click [Test] to run with sample data│
└──────────────────────────────────────────────────────────────┘
```

---

## 7. Implementation Phases

### Phase 1: Foundation (Week 1-2)
- Database model: `dynamic_workflows`, `workflow_runs`, `workflow_step_logs`
- Migration SQL
- `DynamicWorkflowExecutor` Temporal workflow (interprets JSON)
- Step executors: `mcp_tool`, `agent`, `condition`, `transform`
- API routes: CRUD + manual run + run history
- 3 native templates: Daily Briefing, Lead Pipeline, Inbox Monitor

### Phase 2: Triggers & Scheduling (Week 2-3)
- Cron scheduler integration (reuse existing `scheduler_worker.py`)
- Webhook trigger (reuse webhook connectors)
- Event trigger (entity_created, email_received hooks)
- `for_each`, `parallel`, `wait` step types
- Template marketplace (list, install, share)

### Phase 3: Visual Builder (Week 3-5)
- React Flow canvas integration
- Step palette component
- Step configuration panel
- Trigger configurator (cron builder, webhook URL)
- Live test runner (dry-run with sample data)
- Save/load workflow definitions

### Phase 4: Natural Language Creation (Week 5-6)
- `create_dynamic_workflow` MCP tool for Luna
- `run_dynamic_workflow` MCP tool
- `list_dynamic_workflows` MCP tool
- Luna skill instructions for workflow creation
- Intent → JSON workflow mapping

### Phase 5: RL Integration (Week 6-7)
- Score each workflow run (success, duration, cost)
- Track step-level performance per platform/agent
- Optimize: which agent handles which step type best
- Auto-suggest workflow improvements based on run history

---

## 8. Wolfpoint Protocol Integration

Dynamic workflows are the **product** that gets traded in the protocol:

| Protocol Concept | Workflow Feature |
|---|---|
| Agent marketplace | Workflow template marketplace |
| Agent execution | Workflow run on operator node |
| Agent quality score | Workflow success rate + RL score |
| Creator royalty | Workflow template creator earns per-install |
| Node operator | Runs workflow steps on their hardware |

A popular workflow template ("Daily Sales Pipeline") could earn its creator revenue every time someone installs and runs it — exactly like agent execution fees in the protocol.

---

## 9. Dependencies

- **react-flow** or **reactflow** npm package for visual builder
- Existing Temporal infrastructure (already running)
- Existing MCP tools (81+ available as step types)
- Existing webhook connectors (trigger source)
- Existing scheduler_worker (cron execution)
- Existing skill marketplace pattern (template marketplace)
