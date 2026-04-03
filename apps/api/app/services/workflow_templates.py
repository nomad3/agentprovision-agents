"""Native workflow templates — pre-built workflows users can install with one click."""

NATIVE_TEMPLATES = [
    {
        "name": "Daily Briefing",
        "description": "Every morning: scan inbox + calendar, extract key items, send summary via WhatsApp",
        "tier": "native",
        "public": True,
        "tags": ["inbox", "calendar", "briefing", "daily"],
        "trigger_config": {"type": "cron", "schedule": "0 8 * * *", "timezone": "UTC"},
        "definition": {
            "steps": [
                {
                    "id": "scan_inbox",
                    "type": "mcp_tool",
                    "tool": "search_emails",
                    "params": {"query": "is:unread newer_than:1d", "max_results": 20},
                    "output": "emails",
                },
                {
                    "id": "check_calendar",
                    "type": "mcp_tool",
                    "tool": "list_calendar_events",
                    "params": {"days_ahead": 1},
                    "output": "events",
                },
                {
                    "id": "generate_briefing",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Generate my daily briefing.\n\n"
                        "Unread emails:\n{{emails}}\n\n"
                        "Today's calendar:\n{{events}}\n\n"
                        "Format as a concise briefing with: key emails to respond to, "
                        "meetings today, and action items. Keep it short."
                    ),
                    "output": "briefing",
                },
            ],
        },
    },
    {
        "name": "Lead Pipeline",
        "description": "When a new contact is created: score with AI lead rubric, enrich data, notify if hot",
        "tier": "native",
        "public": True,
        "tags": ["leads", "sales", "scoring"],
        "trigger_config": {"type": "event", "event_type": "entity_created"},
        "definition": {
            "steps": [
                {
                    "id": "get_entity",
                    "type": "mcp_tool",
                    "tool": "get_entity",
                    "params": {"entity_id": "{{input.entity_id}}"},
                    "output": "entity",
                },
                {
                    "id": "score",
                    "type": "mcp_tool",
                    "tool": "score_entity",
                    "params": {"entity_id": "{{input.entity_id}}", "rubric": "ai_lead"},
                    "output": "score_result",
                },
                {
                    "id": "check_hot",
                    "type": "condition",
                    "if": "{{score_result.score}} >= 70",
                    "then": "notify",
                    "else": "skip",
                },
                {
                    "id": "notify",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Hot lead detected! {{entity.name}} scored {{score_result.score}}/100.\n"
                        "Reasoning: {{score_result.reasoning}}\n"
                        "Send me a quick summary of this lead."
                    ),
                    "output": "notification",
                },
            ],
        },
    },
    {
        "name": "Competitor Watch",
        "description": "Daily: check competitor entities in knowledge graph, scrape for changes, alert on updates",
        "tier": "native",
        "public": True,
        "tags": ["competitors", "monitoring", "marketing"],
        "trigger_config": {"type": "cron", "schedule": "0 9 * * *", "timezone": "UTC"},
        "definition": {
            "steps": [
                {
                    "id": "list_competitors",
                    "type": "mcp_tool",
                    "tool": "list_competitors",
                    "params": {},
                    "output": "competitors",
                },
                {
                    "id": "analyze",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Review these competitors and check for any recent changes, "
                        "news, or updates:\n{{competitors}}\n\n"
                        "Summarize any notable changes."
                    ),
                    "output": "analysis",
                },
            ],
        },
    },
    {
        "name": "Code Review Pipeline",
        "description": "When a PR is opened: analyze changes, check for issues, post review summary",
        "tier": "native",
        "public": True,
        "tags": ["code", "github", "review"],
        "trigger_config": {"type": "webhook", "webhook_slug": "github-pr"},
        "definition": {
            "steps": [
                {
                    "id": "get_pr",
                    "type": "mcp_tool",
                    "tool": "get_pull_request",
                    "params": {"repo": "{{input.repo}}", "pr_number": "{{input.pr_number}}"},
                    "output": "pr",
                },
                {
                    "id": "review",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Review this pull request:\n"
                        "Title: {{pr.title}}\n"
                        "Description: {{pr.body}}\n"
                        "Files changed: {{pr.files}}\n\n"
                        "Check for: bugs, security issues, code quality, test coverage. "
                        "Be concise."
                    ),
                    "output": "review_result",
                },
            ],
        },
    },
    {
        "name": "Weekly Report",
        "description": "Every Friday: gather metrics from the week, generate summary report, email stakeholders",
        "tier": "native",
        "public": True,
        "tags": ["reports", "weekly", "metrics"],
        "trigger_config": {"type": "cron", "schedule": "0 17 * * 5", "timezone": "UTC"},
        "definition": {
            "steps": [
                {
                    "id": "gather_chat_stats",
                    "type": "mcp_tool",
                    "tool": "search_knowledge",
                    "params": {"query": "conversations tasks completed this week", "max_results": 20},
                    "output": "weekly_context",
                },
                {
                    "id": "generate_report",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Generate a weekly summary report.\n\n"
                        "Context from this week:\n{{weekly_context}}\n\n"
                        "Include: key accomplishments, metrics, issues resolved, "
                        "and priorities for next week. Format as a professional report."
                    ),
                    "output": "report",
                },
            ],
        },
    },
    # ── Tier 1 linear workflow migrations ──────────────────────────────
    {
        "name": "Sales Follow-Up",
        "description": "Wait a configurable delay then execute a follow-up action: send WhatsApp, update pipeline stage, or create reminder",
        "tier": "native",
        "public": True,
        "tags": ["sales", "follow-up", "pipeline"],
        "trigger_config": {"type": "event", "event_type": "follow_up_scheduled"},
        "definition": {
            "steps": [
                {
                    "id": "wait_delay",
                    "type": "wait",
                    "duration": "{{input.delay_hours}}h",
                    "output": "wait_done",
                },
                {
                    "id": "resolve_entity",
                    "type": "mcp_tool",
                    "tool": "get_entity",
                    "params": {"entity_id": "{{input.entity_id}}"},
                    "output": "entity",
                },
                {
                    "id": "execute_followup",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Execute a follow-up action for {{entity.name}}.\n\n"
                        "Action: {{input.action}}\n"
                        "Message: {{input.message}}\n\n"
                        "If action is 'send_whatsapp', send the message via WhatsApp.\n"
                        "If action is 'update_stage', advance the pipeline stage.\n"
                        "If action is 'remind', create a reminder notification."
                    ),
                    "output": "followup_result",
                },
            ],
        },
    },
    {
        "name": "Monthly Billing",
        "description": "1st of each month: aggregate completed visits per clinic, generate invoices, send them, schedule payment follow-ups",
        "tier": "native",
        "public": True,
        "tags": ["billing", "invoices", "monthly", "healthpets"],
        "trigger_config": {"type": "cron", "schedule": "0 6 1 * *", "timezone": "UTC"},
        "definition": {
            "steps": [
                {
                    "id": "aggregate_visits",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/billing/aggregate",
                    "body": {"month": "{{input.month}}", "clinic_ids": "{{input.clinic_ids}}"},
                    "output": "visits",
                },
                {
                    "id": "generate_invoices",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/billing/invoices",
                    "body": {"month": "{{input.month}}", "clinics": "{{visits.clinics}}"},
                    "output": "invoices",
                },
                {
                    "id": "send_invoices",
                    "type": "mcp_tool",
                    "tool": "send_email",
                    "params": {
                        "subject": "Invoice for {{input.month}}",
                        "body": "Please find your invoice attached for billing period {{input.month}}.",
                        "invoice_ids": "{{invoices.invoice_ids}}",
                    },
                    "output": "delivery",
                },
                {
                    "id": "schedule_payment_followups",
                    "type": "mcp_tool",
                    "tool": "schedule_followup",
                    "params": {
                        "entity_ids": "{{invoices.invoice_ids}}",
                        "delay_days": 7,
                        "action": "payment_reminder",
                    },
                    "output": "followups",
                },
            ],
        },
    },
    {
        "name": "Dataset Sync (Bronze/Silver)",
        "description": "Sync a dataset to Databricks Unity Catalog: create Bronze external table, transform to Silver managed table, update metadata",
        "tier": "native",
        "public": True,
        "tags": ["data", "databricks", "etl", "sync"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "sync_bronze",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/datasets/{{input.dataset_id}}/sync-bronze",
                    "body": {"tenant_id": "{{input.tenant_id}}"},
                    "output": "bronze_result",
                },
                {
                    "id": "transform_silver",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/datasets/{{input.dataset_id}}/transform-silver",
                    "body": {
                        "bronze_table": "{{bronze_result.bronze_table}}",
                        "tenant_id": "{{input.tenant_id}}",
                    },
                    "output": "silver_result",
                },
                {
                    "id": "update_metadata",
                    "type": "internal_api",
                    "method": "PATCH",
                    "path": "/api/v1/datasets/{{input.dataset_id}}",
                    "body": {
                        "sync_status": "synced",
                        "bronze_table": "{{bronze_result.bronze_table}}",
                        "silver_table": "{{silver_result.silver_table}}",
                        "row_count": "{{bronze_result.row_count}}",
                    },
                    "output": "metadata_updated",
                },
            ],
        },
    },
    {
        "name": "Data Source Sync",
        "description": "Extract data from any connector, load to Databricks Bronze and Silver layers, update sync metadata",
        "tier": "native",
        "public": True,
        "tags": ["data", "connectors", "etl", "sync"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "extract_data",
                    "type": "mcp_tool",
                    "tool": "query_data_source",
                    "params": {
                        "connector_id": "{{input.connector_id}}",
                        "connector_type": "{{input.connector_type}}",
                        "mode": "{{input.sync_mode}}",
                        "table_name": "{{input.table_name}}",
                        "watermark_column": "{{input.watermark_column}}",
                        "last_watermark": "{{input.last_watermark}}",
                    },
                    "output": "extract_result",
                },
                {
                    "id": "load_bronze",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/datasources/{{input.connector_id}}/load-bronze",
                    "body": {
                        "staging_path": "{{extract_result.staging_path}}",
                        "schema": "{{extract_result.schema}}",
                        "target_dataset": "{{input.target_dataset}}",
                    },
                    "output": "bronze_result",
                },
                {
                    "id": "transform_silver",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/datasources/{{input.connector_id}}/transform-silver",
                    "body": {"bronze_table": "{{bronze_result.bronze_table}}"},
                    "output": "silver_result",
                },
                {
                    "id": "update_sync_metadata",
                    "type": "internal_api",
                    "method": "PATCH",
                    "path": "/api/v1/datasources/{{input.connector_id}}/sync-status",
                    "body": {
                        "last_sync_status": "success",
                        "rows_synced": "{{extract_result.row_count}}",
                        "bronze_table": "{{bronze_result.bronze_table}}",
                        "silver_table": "{{silver_result.silver_table}}",
                        "new_watermark": "{{extract_result.new_watermark}}",
                    },
                    "output": "sync_metadata",
                },
            ],
        },
    },
    {
        "name": "Embedding Backfill",
        "description": "One-shot backfill of vector embeddings for knowledge entities, memories, and observations",
        "tier": "native",
        "public": True,
        "tags": ["embeddings", "knowledge", "backfill", "maintenance"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "backfill_entities",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/knowledge/embeddings/backfill",
                    "body": {"target": "entities", "tenant_id": "{{input.tenant_id}}"},
                    "output": "entity_results",
                },
                {
                    "id": "backfill_memories",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/knowledge/embeddings/backfill",
                    "body": {"target": "memories", "tenant_id": "{{input.tenant_id}}"},
                    "output": "memory_results",
                },
                {
                    "id": "backfill_observations",
                    "type": "internal_api",
                    "method": "POST",
                    "path": "/api/v1/knowledge/embeddings/backfill",
                    "body": {"target": "observations", "tenant_id": "{{input.tenant_id}}"},
                    "output": "observation_results",
                },
            ],
        },
    },
    # ── Tier 2 branching workflow migrations ──────────────────────────
    {
        "name": "Deal Pipeline",
        "description": "M&A deal pipeline: discover prospects, score for sell-likelihood, research high-scorers, generate outreach, advance pipeline, sync to knowledge graph",
        "tier": "native",
        "public": True,
        "tags": ["deals", "sales", "pipeline", "m&a"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "discover",
                    "type": "mcp_tool",
                    "tool": "find_entities",
                    "params": {
                        "category": "prospect",
                        "query": "{{input.industry}}",
                        "criteria": "{{input.criteria}}",
                    },
                    "output": "prospects",
                },
                {
                    "id": "score",
                    "type": "mcp_tool",
                    "tool": "qualify_lead",
                    "params": {
                        "entity_ids": "{{prospects.entity_ids}}",
                        "rubric": "sell_likelihood",
                    },
                    "output": "score_results",
                },
                {
                    "id": "filter_hot",
                    "type": "condition",
                    "if": "{{score_results.high_scorers | length}} > 0",
                    "then": "research",
                    "else": "skip",
                },
                {
                    "id": "research",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Generate detailed research briefs for these high-scoring prospects:\n"
                        "{{score_results.high_scorers}}\n\n"
                        "For each prospect include: company overview, financials, "
                        "recent news, key decision-makers, and sell-likelihood rationale."
                    ),
                    "output": "research_briefs",
                },
                {
                    "id": "outreach",
                    "type": "mcp_tool",
                    "tool": "draft_outreach",
                    "params": {
                        "entity_ids": "{{score_results.high_scorer_ids}}",
                        "outreach_type": "{{input.outreach_type | default('cold_email')}}",
                        "context": "{{research_briefs}}",
                    },
                    "output": "outreach_drafts",
                },
                {
                    "id": "advance",
                    "type": "mcp_tool",
                    "tool": "update_pipeline_stage",
                    "params": {
                        "entity_ids": "{{score_results.high_scorer_ids}}",
                        "stage": "contacted",
                    },
                    "output": "advance_result",
                },
                {
                    "id": "sync_kg",
                    "type": "mcp_tool",
                    "tool": "record_observation",
                    "params": {
                        "entity_ids": "{{prospects.entity_ids}}",
                        "observation": "Deal pipeline run completed. {{score_results.high_scorers | length}} prospects above threshold, outreach generated.",
                    },
                    "output": "sync_result",
                },
            ],
        },
    },
    {
        "name": "Prospecting Pipeline",
        "description": "Outbound lead generation: enrich prospects, score, qualify by threshold, draft personalised outreach for each qualified lead, notify results",
        "tier": "native",
        "public": True,
        "tags": ["prospecting", "leads", "outbound", "sales"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "research",
                    "type": "mcp_tool",
                    "tool": "find_entities",
                    "params": {
                        "entity_ids": "{{input.entity_ids}}",
                        "enrich": True,
                    },
                    "output": "enriched_prospects",
                },
                {
                    "id": "score",
                    "type": "mcp_tool",
                    "tool": "qualify_lead",
                    "params": {
                        "entity_ids": "{{input.entity_ids}}",
                        "rubric_id": "{{input.rubric_id}}",
                    },
                    "output": "score_results",
                },
                {
                    "id": "qualify",
                    "type": "condition",
                    "if": "{{score_results.qualified_ids | length}} > 0",
                    "then": "outreach_loop",
                    "else": "notify",
                },
                {
                    "id": "outreach_loop",
                    "type": "for_each",
                    "collection": "{{score_results.qualified_ids}}",
                    "as": "prospect_id",
                    "steps": [
                        {
                            "id": "draft_outreach",
                            "type": "mcp_tool",
                            "tool": "draft_outreach",
                            "params": {
                                "entity_id": "{{prospect_id}}",
                                "template": "{{input.template | default('default')}}",
                            },
                            "output": "outreach_draft",
                        },
                    ],
                },
                {
                    "id": "notify",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Prospecting pipeline complete.\n\n"
                        "Total entities: {{input.entity_ids | length}}\n"
                        "Qualified: {{score_results.qualified_ids | length}}\n"
                        "Outreach drafts generated for qualified leads.\n\n"
                        "Summarize the results and highlight the top prospects."
                    ),
                    "output": "notification",
                },
            ],
        },
    },
    {
        "name": "Remedia Order",
        "description": "E-commerce order lifecycle: create order, send WhatsApp confirmation, await payment approval, confirm payment, track delivery",
        "tier": "native",
        "public": True,
        "tags": ["ecommerce", "orders", "whatsapp", "remedia"],
        "trigger_config": {"type": "manual"},
        "definition": {
            "steps": [
                {
                    "id": "create_order",
                    "type": "mcp_tool",
                    "tool": "call_mcp_tool",
                    "params": {
                        "server": "remedia",
                        "tool": "create_order",
                        "pharmacy_id": "{{input.pharmacy_id}}",
                        "items": "{{input.items}}",
                        "payment_provider": "{{input.payment_provider | default('mercadopago')}}",
                    },
                    "output": "order",
                },
                {
                    "id": "send_confirmation",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Send order confirmation to {{input.phone_number}} via WhatsApp.\n\n"
                        "Order ID: {{order.order_id}}\n"
                        "Total: ${{order.total}}\n"
                        "Payment link: {{order.payment_url}}\n\n"
                        "Send a friendly confirmation message with the payment link."
                    ),
                    "output": "confirmation_sent",
                },
                {
                    "id": "await_payment",
                    "type": "human_approval",
                    "prompt": "Waiting for payment on order {{order.order_id}} (${{order.total}}). Payment will be confirmed automatically or can be manually approved.",
                    "timeout_minutes": 30,
                },
                {
                    "id": "check_payment",
                    "type": "condition",
                    "if": "{{await_payment.approved}} == true",
                    "then": "notify_payment",
                    "else": "notify_timeout",
                },
                {
                    "id": "notify_payment",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Payment confirmed for order {{order.order_id}}!\n"
                        "Notify {{input.phone_number}} via WhatsApp that payment of "
                        "${{order.total}} was received and the order is being prepared."
                    ),
                    "output": "payment_notification",
                },
                {
                    "id": "notify_timeout",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Payment not received for order {{order.order_id}} within 30 minutes.\n"
                        "Send a gentle reminder to {{input.phone_number}} via WhatsApp "
                        "with the payment link: {{order.payment_url}}"
                    ),
                    "output": "timeout_notification",
                },
                {
                    "id": "track_delivery",
                    "type": "mcp_tool",
                    "tool": "call_mcp_tool",
                    "params": {
                        "server": "remedia",
                        "tool": "track_delivery",
                        "order_id": "{{order.order_id}}",
                    },
                    "output": "delivery_status",
                },
            ],
        },
    },
    {
        "name": "Auto Action Router",
        "description": "Intent-based action router: classify action type and branch to the appropriate handler (email, WhatsApp, research, analysis, or task creation)",
        "tier": "native",
        "public": True,
        "tags": ["automation", "routing", "actions", "memory"],
        "trigger_config": {"type": "event", "event_type": "action_triggered"},
        "definition": {
            "steps": [
                {
                    "id": "classify",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Classify this action request and extract the intent.\n\n"
                        "Action type: {{input.action_type}}\n"
                        "Entity: {{input.entity_id}}\n"
                        "Context: {{input.context}}\n\n"
                        "Return the best action category: reply_email, send_whatsapp, "
                        "research, analyze, or create_task."
                    ),
                    "output": "classification",
                },
                {
                    "id": "route_email",
                    "type": "condition",
                    "if": "{{input.action_type}} == 'reply_email'",
                    "then": "handle_email",
                    "else": "route_whatsapp",
                },
                {
                    "id": "handle_email",
                    "type": "mcp_tool",
                    "tool": "send_email",
                    "params": {
                        "entity_id": "{{input.entity_id}}",
                        "context": "{{input.context}}",
                        "draft": True,
                    },
                    "output": "email_result",
                },
                {
                    "id": "route_whatsapp",
                    "type": "condition",
                    "if": "{{input.action_type}} == 'send_whatsapp'",
                    "then": "handle_whatsapp",
                    "else": "route_research",
                },
                {
                    "id": "handle_whatsapp",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Send a WhatsApp message regarding entity {{input.entity_id}}.\n\n"
                        "Context: {{input.context}}\n\n"
                        "Draft and send an appropriate message."
                    ),
                    "output": "whatsapp_result",
                },
                {
                    "id": "route_research",
                    "type": "condition",
                    "if": "{{input.action_type}} == 'research'",
                    "then": "handle_research",
                    "else": "route_analyze",
                },
                {
                    "id": "handle_research",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Research entity {{input.entity_id}}.\n\n"
                        "Context: {{input.context}}\n\n"
                        "Conduct thorough research and store findings in the knowledge graph."
                    ),
                    "output": "research_result",
                },
                {
                    "id": "route_analyze",
                    "type": "condition",
                    "if": "{{input.action_type}} == 'analyze'",
                    "then": "handle_analyze",
                    "else": "handle_task",
                },
                {
                    "id": "handle_analyze",
                    "type": "agent",
                    "agent": "luna",
                    "prompt": (
                        "Analyze entity {{input.entity_id}}.\n\n"
                        "Context: {{input.context}}\n\n"
                        "Provide a detailed analysis and record insights."
                    ),
                    "output": "analysis_result",
                },
                {
                    "id": "handle_task",
                    "type": "mcp_tool",
                    "tool": "create_jira_issue",
                    "params": {
                        "summary": "Auto-action: {{input.context}}",
                        "description": "Automated task for entity {{input.entity_id}}.\n\nContext: {{input.context}}",
                        "issue_type": "Task",
                    },
                    "output": "task_result",
                },
            ],
        },
    },
]


def seed_native_templates(db, tenant_id=None):
    """Seed native workflow templates. Idempotent — skips existing."""
    import uuid
    from app.models.dynamic_workflow import DynamicWorkflow

    created = 0
    for tmpl in NATIVE_TEMPLATES:
        existing = db.query(DynamicWorkflow).filter(
            DynamicWorkflow.name == tmpl["name"],
            DynamicWorkflow.tier == "native",
        ).first()
        if existing:
            continue

        wf = DynamicWorkflow(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(tenant_id) if tenant_id else uuid.UUID("00000000-0000-0000-0000-000000000000"),
            name=tmpl["name"],
            description=tmpl["description"],
            definition=tmpl["definition"],
            trigger_config=tmpl["trigger_config"],
            tags=tmpl["tags"],
            tier="native",
            public=True,
            status="draft",
        )
        db.add(wf)
        created += 1

    db.commit()
    return created
