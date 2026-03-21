# Dynamic Workflows — Implementation Plan

> Temporal-native dynamic workflows with full durability guarantees. Not n8n — every step is a real Temporal activity with crash recovery, retry, heartbeating, and exactly-once semantics.

**Date:** 2026-03-21
**Status:** Ready to execute
**Depends on:** `2026-03-21-dynamic-workflows-design.md`

---

## Core Principle

**JSON defines WHAT runs. Temporal guarantees HOW RELIABLY it runs.**

Every dynamic workflow step becomes a real Temporal activity with:
- Per-step timeout (30s for tools, 10min for agents, 30 days for human approval)
- Per-step retry policy (tools: 3x, agents: 2x, conditions: no retry)
- Heartbeating for long-running steps
- Crash recovery — resumes at the exact step that was interrupted
- `for_each` loops use child workflows — each iteration independently durable
- `continue_as_new` for infinite-duration workflows (monitors, pollers)

---

## Phase 1: Foundation (Tasks 1-6)

### Task 1: Database Migration

**File:** `apps/api/migrations/050_dynamic_workflows.sql`

```sql
CREATE TABLE dynamic_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    definition JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    trigger_config JSONB,
    created_by UUID,
    tags TEXT[] DEFAULT '{}',
    tier VARCHAR(20) DEFAULT 'custom',
    source_template_id UUID,
    public BOOLEAN DEFAULT false,
    installs INT DEFAULT 0,
    rating FLOAT,
    run_count INT DEFAULT 0,
    last_run_at TIMESTAMP,
    avg_duration_ms INT,
    success_rate FLOAT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_dw_tenant ON dynamic_workflows(tenant_id);
CREATE INDEX idx_dw_status ON dynamic_workflows(tenant_id, status);
CREATE INDEX idx_dw_tier ON dynamic_workflows(tier);

CREATE TABLE workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    workflow_id UUID NOT NULL REFERENCES dynamic_workflows(id) ON DELETE CASCADE,
    workflow_version INT,
    trigger_type VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP,
    duration_ms INT,
    step_results JSONB DEFAULT '{}',
    error TEXT,
    input_data JSONB,
    output_data JSONB,
    total_tokens INT DEFAULT 0,
    total_cost_usd FLOAT DEFAULT 0,
    platform VARCHAR(50)
);

CREATE INDEX idx_wr_workflow ON workflow_runs(workflow_id);
CREATE INDEX idx_wr_tenant ON workflow_runs(tenant_id);
CREATE INDEX idx_wr_status ON workflow_runs(status);

CREATE TABLE workflow_step_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    step_id VARCHAR(100) NOT NULL,
    step_type VARCHAR(50),
    step_name VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INT,
    input_data JSONB,
    output_data JSONB,
    error TEXT,
    tokens_used INT DEFAULT 0,
    cost_usd FLOAT DEFAULT 0,
    platform VARCHAR(50),
    retry_count INT DEFAULT 0
);

CREATE INDEX idx_wsl_run ON workflow_step_logs(run_id);
```

### Task 2: SQLAlchemy Models

**File:** `apps/api/app/models/dynamic_workflow.py`

- `DynamicWorkflow` — workflow definition with tenant_id, definition JSONB, status, trigger_config
- `WorkflowRun` — execution instance with status, step_results, cost tracking
- `WorkflowStepLog` — per-step execution log

Register in `models/__init__.py`.

### Task 3: Pydantic Schemas

**File:** `apps/api/app/schemas/dynamic_workflow.py`

Schemas:
- `WorkflowStepDef` — step definition (type, tool, params, output, conditions)
- `WorkflowTriggerDef` — trigger config (type, schedule, webhook_slug)
- `DynamicWorkflowCreate` — name, description, definition, trigger_config
- `DynamicWorkflowUpdate` — partial update
- `DynamicWorkflowInDB` — full response with stats
- `WorkflowRunInDB` — run details
- `WorkflowStepLogInDB` — step log details

Validate workflow definitions at create/update time:
- All step IDs unique
- Referenced outputs exist in prior steps
- MCP tool names are valid (check against registry)
- Trigger config is valid (cron parseable, etc.)

### Task 4: Temporal Workflow Executor

**File:** `apps/api/app/workflows/dynamic_executor.py`

The core engine. A single Temporal workflow class that executes any dynamic workflow definition:

```python
@workflow.defn
class DynamicWorkflowExecutor:
    """Execute a dynamic workflow from its JSON definition.

    Every step becomes a Temporal activity with:
    - Typed timeouts (30s tools, 10min agents, 30d approvals)
    - Retry policies (3x tools, 2x agents, 1x conditions)
    - Heartbeating for long-running steps
    - Step-level crash recovery via Temporal replay
    """

    @workflow.run
    async def run(self, input: DynamicWorkflowInput) -> DynamicWorkflowResult:
        ctx = WorkflowContext(input.input_data, input.tenant_id)

        for step in input.definition["steps"]:
            if step["type"] == "for_each":
                # Child workflow per iteration — independently durable
                result = await self._execute_for_each(step, ctx)
            elif step["type"] == "parallel":
                # Concurrent activity execution
                result = await self._execute_parallel(step, ctx)
            elif step["type"] == "human_approval":
                # Signal-based wait — survives days/weeks
                result = await self._wait_for_approval(step, ctx)
            elif step["type"] == "wait":
                # Temporal timer — survives crashes
                await workflow.sleep(parse_duration(step["duration"]))
                result = {"waited": step["duration"]}
            else:
                # Standard activity execution
                result = await workflow.execute_activity(
                    execute_dynamic_step,
                    args=[step, ctx.snapshot(), input.tenant_id],
                    start_to_close_timeout=_timeout_for(step),
                    heartbeat_timeout=_heartbeat_for(step),
                    retry_policy=_retry_for(step),
                )

            ctx.set(step["id"], result)

            # Condition branching
            if step["type"] == "condition" and not result.get("passed"):
                if step.get("else") == "skip":
                    continue
                elif step.get("else"):
                    # Jump to a specific step
                    pass  # Phase 2

        return DynamicWorkflowResult(
            status="completed",
            output=ctx.output(),
            total_tokens=ctx.total_tokens,
            total_cost=ctx.total_cost,
        )

    async def _execute_for_each(self, step, ctx):
        """Each iteration is a child workflow — independently durable."""
        collection = ctx.resolve(step["collection"])
        results = []
        for i, item in enumerate(collection):
            result = await workflow.execute_child_workflow(
                DynamicWorkflowExecutor.run,
                DynamicWorkflowInput(
                    definition={"steps": step["steps"]},
                    input_data={step["as"]: item, **ctx.snapshot()},
                    tenant_id=ctx.tenant_id,
                ),
                id=f"{workflow.info().workflow_id}-foreach-{i}",
            )
            results.append(result)
        return results

    async def _execute_parallel(self, step, ctx):
        """Run steps concurrently, wait for all to complete."""
        tasks = []
        for sub_step in step["steps"]:
            tasks.append(
                workflow.execute_activity(
                    execute_dynamic_step,
                    args=[sub_step, ctx.snapshot(), ctx.tenant_id],
                    start_to_close_timeout=_timeout_for(sub_step),
                    retry_policy=_retry_for(sub_step),
                )
            )
        return await asyncio.gather(*tasks)

    @workflow.signal
    async def approve(self, step_id: str, approved: bool):
        """Signal handler for human approval steps."""
        self._approvals[step_id] = approved

    async def _wait_for_approval(self, step, ctx):
        """Wait for human signal — survives days/weeks of waiting."""
        self._approvals = getattr(self, '_approvals', {})
        await workflow.wait_condition(
            lambda: step["id"] in self._approvals,
            timeout=timedelta(days=30),
        )
        return {"approved": self._approvals.get(step["id"], False)}
```

### Task 5: Step Executor Activity

**File:** `apps/api/app/workflows/activities/dynamic_step.py`

The activity that executes individual steps:

```python
@activity.defn
async def execute_dynamic_step(
    step: dict,
    context: dict,
    tenant_id: str,
) -> dict:
    """Execute a single workflow step. Each call is a Temporal activity
    with full retry/timeout/heartbeat support."""

    step_type = step["type"]
    params = resolve_templates(step.get("params", {}), context)

    if step_type == "mcp_tool":
        activity.heartbeat(f"Calling MCP tool: {step['tool']}")
        return await call_mcp_tool(
            tool_name=step["tool"],
            params={**params, "tenant_id": tenant_id},
        )

    elif step_type == "agent":
        activity.heartbeat(f"Running agent: {step.get('agent', 'luna')}")
        prompt = resolve_template(step["prompt"], context)
        return await call_agent(
            agent_slug=step.get("agent", "luna"),
            message=prompt,
            tenant_id=tenant_id,
        )

    elif step_type == "condition":
        expression = resolve_template(step["if"], context)
        return {"passed": evaluate_expression(expression, context)}

    elif step_type == "transform":
        return transform_data(step["operation"], step.get("input"), context)

    elif step_type == "webhook_trigger":
        # This step type is handled by the trigger system, not here
        return {"triggered": True}

    elif step_type == "workflow":
        # Delegate to child workflow (handled in executor)
        return {"delegated": step.get("workflow_id")}

    else:
        raise ValueError(f"Unknown step type: {step_type}")
```

Helper functions:

```python
async def call_mcp_tool(tool_name: str, params: dict) -> dict:
    """Call an MCP tool via the internal API."""
    async with httpx.AsyncClient(timeout=25.0) as client:
        resp = await client.post(
            f"{API_BASE_URL}/mcp",
            json={"method": "tools/call", "params": {"name": tool_name, "arguments": params}},
            headers={"X-Internal-Key": API_INTERNAL_KEY},
        )
        return resp.json()

async def call_agent(agent_slug: str, message: str, tenant_id: str) -> dict:
    """Call an agent via the CLI session manager."""
    from app.services.agent_router import route_and_execute
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        response, metadata = route_and_execute(
            db, tenant_id=uuid.UUID(tenant_id),
            user_id=uuid.UUID(tenant_id),  # System actor
            message=message, agent_slug=agent_slug,
            channel="workflow",
        )
        return {"response": response, "metadata": metadata}
    finally:
        db.close()

def resolve_template(template: str, context: dict) -> str:
    """Replace {{var}} placeholders with context values."""
    import re
    def replacer(match):
        path = match.group(1).strip()
        value = context
        for key in path.split('.'):
            if isinstance(value, dict):
                value = value.get(key, f'{{{{{path}}}}}')
            elif isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                return f'{{{{{path}}}}}'
        return str(value)
    return re.sub(r'\{\{(.+?)\}\}', replacer, template)

def evaluate_expression(expr: str, context: dict) -> bool:
    """Safely evaluate a simple condition expression."""
    # Support: ==, !=, >, <, >=, <=, contains, startswith
    import operator
    ops = {
        '>=': operator.ge, '<=': operator.le,
        '>': operator.gt, '<': operator.lt,
        '==': operator.eq, '!=': operator.ne,
    }
    for op_str, op_fn in ops.items():
        if op_str in expr:
            left, right = expr.split(op_str, 1)
            left = resolve_template(left.strip(), context)
            right = right.strip().strip('"\'')
            try:
                return op_fn(float(left), float(right))
            except ValueError:
                return op_fn(left, right)
    return bool(resolve_template(expr, context))
```

### Task 6: API Routes

**File:** `apps/api/app/api/v1/dynamic_workflows.py`

Routes:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/workflows/dynamic` | Create workflow |
| GET | `/workflows/dynamic` | List tenant workflows |
| GET | `/workflows/dynamic/{id}` | Get workflow detail |
| PUT | `/workflows/dynamic/{id}` | Update workflow |
| DELETE | `/workflows/dynamic/{id}` | Delete workflow |
| POST | `/workflows/dynamic/{id}/run` | Trigger manual run |
| POST | `/workflows/dynamic/{id}/activate` | Set status to active |
| POST | `/workflows/dynamic/{id}/pause` | Pause workflow |
| GET | `/workflows/dynamic/{id}/runs` | List runs for workflow |
| GET | `/workflows/dynamic/runs/{run_id}` | Get run details + step logs |
| POST | `/workflows/dynamic/runs/{run_id}/approve/{step_id}` | Approve/reject human step |
| GET | `/workflows/dynamic/templates` | List available templates |
| POST | `/workflows/dynamic/templates/{id}/install` | Install template |

Mount in `routes.py`.

---

## Phase 2: Triggers & Templates (Tasks 7-10)

### Task 7: Cron Scheduler Integration

Extend existing `scheduler_worker.py` to poll `dynamic_workflows` where:
- `status = 'active'`
- `trigger_config->>'type' = 'cron'`
- Next run time has passed

Start `DynamicWorkflowExecutor` via Temporal for each due workflow.

### Task 8: Event Triggers

Hook into existing systems to trigger workflows on events:
- `entity_created` → after `knowledge_service.create_entity()`
- `email_received` → after `InboxMonitorWorkflow` fetches new emails
- `pr_merged` → after `git_history` activity detects merged PR
- `webhook_received` → after webhook connector inbound endpoint

Each event checks `dynamic_workflows` for matching triggers and starts execution.

### Task 9: Native Templates

Create 5 native workflow templates as seed data:

1. **Daily Briefing** — cron 8am → scan inbox + calendar → summarize → WhatsApp
2. **Lead Pipeline** — event:entity_created → score → enrich → notify if hot
3. **Competitor Watch** — daily → scrape competitors → compare → alert changes
4. **Invoice Processor** — event:email_received → detect invoice → extract data → create entity
5. **Weekly Report** — cron Friday 5pm → query metrics → generate report → email

### Task 10: Template Marketplace API

- List templates (native + community + public custom)
- Install template → copies definition to tenant's workflows
- Rate templates
- Share custom workflow as template (set public=true)

---

## Phase 3: MCP Tools for Luna (Tasks 11-13)

### Task 11: Workflow MCP Tools

**File:** `apps/mcp-server/src/mcp_tools/workflows.py`

6 MCP tools for Luna to manage workflows via chat:

- `create_dynamic_workflow` — create from description or JSON definition
- `list_dynamic_workflows` — list tenant's workflows with status
- `run_dynamic_workflow` — trigger manual execution
- `get_workflow_status` — check run status and step results
- `update_dynamic_workflow` — modify steps or trigger
- `install_workflow_template` — install from template marketplace

### Task 12: Natural Language → Workflow JSON

When Luna receives a workflow creation request like "every morning scan my inbox and score leads", she:

1. Identifies it's a workflow request (not a one-off task)
2. Calls `create_dynamic_workflow` with a description
3. The tool maps natural language to workflow JSON:
   - "every morning" → `trigger: {type: "cron", schedule: "0 8 * * *"}`
   - "scan my inbox" → `step: {type: "mcp_tool", tool: "search_emails"}`
   - "score leads" → `step: {type: "mcp_tool", tool: "score_entity"}`
4. Returns the workflow for user confirmation
5. Activates on approval

### Task 13: Luna Skill Update

Add workflow instructions to Luna's skill.md:
- When user asks for automated/recurring tasks, create a dynamic workflow
- When user asks "what workflows do I have", call list_dynamic_workflows
- When user asks to run something, check if a matching workflow exists first

---

## Phase 4: Visual Builder (Tasks 14-17)

### Task 14: React Flow Integration

Install `reactflow` package. Create `WorkflowBuilder` component.

### Task 15: Step Palette

Sidebar component listing all available step types:
- MCP Tools (grouped by category: email, calendar, knowledge, etc.)
- Agent steps (Luna, Code, Data)
- Logic (condition, for_each, parallel)
- Flow (wait, human_approval, webhook_trigger)
- Sub-workflows

### Task 16: Step Configuration Panel

Right panel that shows when a step is selected:
- Step type selector
- Tool/agent picker
- Parameter inputs (dynamic based on tool schema)
- Output variable name
- Condition expression builder
- Timeout and retry overrides

### Task 17: Test Runner

"Test" button that:
- Runs the workflow with sample data
- Shows step-by-step execution in real-time
- Displays inputs/outputs per step
- Shows total tokens and cost

---

## Phase 5: RL Integration (Tasks 18-19)

### Task 18: Workflow Run Scoring

After each run completes:
- Log RL experience with `decision_point = "workflow_execution"`
- State: workflow_id, step_count, trigger_type
- Action: platforms used, agents invoked, tools called
- Reward: auto-quality score of the output (if applicable) + success/failure
- Track cost: total tokens, total USD across all steps

### Task 19: Step-Level Platform Optimization

For agent steps, track which platform (Claude/Gemini/Codex) produced the best results:
- Same step, different platforms → compare quality scores
- RL learns: "for email summarization, Gemini is 20% cheaper with same quality"
- Auto-route agent steps to the optimal platform

---

## File Inventory

### New Files (Phase 1)

| File | Description |
|------|-------------|
| `apps/api/migrations/050_dynamic_workflows.sql` | DB tables |
| `apps/api/app/models/dynamic_workflow.py` | SQLAlchemy models |
| `apps/api/app/schemas/dynamic_workflow.py` | Pydantic schemas |
| `apps/api/app/services/dynamic_workflows.py` | Service layer (CRUD + validation) |
| `apps/api/app/api/v1/dynamic_workflows.py` | API routes |
| `apps/api/app/workflows/dynamic_executor.py` | Temporal workflow executor |
| `apps/api/app/workflows/activities/dynamic_step.py` | Step executor activity |

### Modified Files (Phase 1)

| File | Change |
|------|--------|
| `apps/api/app/api/v1/routes.py` | Mount dynamic_workflows router |
| `apps/api/app/models/__init__.py` | Register new models |
| `apps/api/app/workers/orchestration_worker.py` | Register DynamicWorkflowExecutor |

### New Files (Phase 3)

| File | Description |
|------|-------------|
| `apps/mcp-server/src/mcp_tools/dynamic_workflows.py` | 6 MCP tools |

### New Files (Phase 4)

| File | Description |
|------|-------------|
| `apps/web/src/components/workflows/WorkflowBuilder.js` | Visual editor canvas |
| `apps/web/src/components/workflows/StepPalette.js` | Step type sidebar |
| `apps/web/src/components/workflows/StepConfig.js` | Step configuration panel |
| `apps/web/src/components/workflows/TestRunner.js` | Test execution panel |

---

## Timeline

| Phase | Tasks | Duration | What Ships |
|-------|-------|----------|------------|
| 1 | 1-6 | Week 1-2 | DB + models + executor + API. Users can create/run workflows via API. |
| 2 | 7-10 | Week 2-3 | Cron triggers, event triggers, 5 native templates, marketplace. |
| 3 | 11-13 | Week 3-4 | Luna can create/manage workflows via chat. |
| 4 | 14-17 | Week 4-6 | Visual drag-drop builder with test runner. |
| 5 | 18-19 | Week 6-7 | RL scoring per run, cross-platform step optimization. |

---

## Comparison: Our Approach vs Others

| Feature | n8n/Zapier | Temporal (hardcoded) | Wolfpoint Dynamic |
|---------|-----------|---------------------|-------------------|
| Crash recovery | None | Full | Full (Temporal) |
| Retry semantics | Basic | Per-activity typed | Per-step typed |
| Long-running (days) | Timeout | continue_as_new | continue_as_new |
| Human approval | Polling | Signals | Signals |
| Loop durability | None | Child workflows | Child workflows |
| Creation method | UI only | Code only | UI + NL + Code + Templates |
| Marketplace | n8n templates | None | Full marketplace with ratings |
| RL optimization | None | None | Auto-scoring + platform routing |
| Cost tracking | None | None | Per-step tokens + USD |
| Cross-platform | No | No | Claude vs Gemini vs Codex per step |
