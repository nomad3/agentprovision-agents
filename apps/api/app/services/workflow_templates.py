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
