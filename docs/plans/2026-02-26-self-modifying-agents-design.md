# Multi-Team Agent Hierarchy — Self-Modifying Dev Team + Restructured Organization

**Goal:** Restructure the ADK agent hierarchy from a flat 6-agent model into a team-based organization with 4 specialized teams + a personal assistant co-pilot. The dev_team enables agents to modify their own codebase and deploy changes autonomously.

**Architecture:** The root supervisor routes to 5 top-level entities: personal_assistant, dev_team, data_team, sales_team, and marketing_team. Each team has a sub-supervisor that coordinates its specialist agents. The dev_team enforces a strict 5-step development cycle (architect -> coder -> tester -> dev_ops -> user_agent). Other teams use flexible routing. All dev agents share shell access via `execute_shell`; only dev_ops can deploy via `deploy_changes`.

## Agent Hierarchy

```
root_supervisor (routing only — no tools)
  │
  ├── personal_assistant    — "Luna", WhatsApp-native business co-pilot
  │
  ├── dev_team (sub-supervisor, strict cycle)
  │     ├── architect       — explore codebase, design solutions, write specs
  │     ├── coder           — implement code via shell
  │     ├── tester          — write & run tests
  │     ├── dev_ops         — git commit/push, deploy, monitor
  │     └── user_agent      — smoke-test deployed changes
  │
  ├── data_team (sub-supervisor, flexible routing)
  │     ├── data_analyst    — SQL queries, statistical analysis, dataset ops
  │     └── report_generator — reports, visualizations, formatted exports
  │
  ├── sales_team (sub-supervisor, flexible routing)
  │     ├── sales_agent     — lead qualification, outreach, pipeline, proposals
  │     └── customer_support — FAQ, order lookups, complaints, general chat
  │
  └── marketing_team (sub-supervisor, flexible routing)
        ├── web_researcher   — web scraping, search, lead generation
        └── knowledge_manager — entity CRUD, knowledge graph, scoring
```

## New Tools

### `tools/shell_tools.py`

**`execute_shell(command, working_dir, timeout)`**
- Runs any shell command via `subprocess.run(command, shell=True, capture_output=True)`
- Parameters:
  - `command` (str): The shell command to execute
  - `working_dir` (str, default="/app"): Working directory
  - `timeout` (int, default=60, max=300): Seconds before kill
- Returns: `{"stdout": str, "stderr": str, "return_code": int, "command": str}`
- Output truncated to 10KB stdout / 5KB stderr to fit LLM context
- No command filtering — full access within container boundaries

**`deploy_changes(commit_message, files)`**
- Stages, commits, and pushes code changes to the git repo
- Parameters:
  - `commit_message` (str): Git commit message
  - `files` (list[str], optional): Specific files to stage. If None, stages all changes.
- Returns: `{"status": "pushed", "commit_sha": str, "files_changed": list[str], "deploy_triggered": bool}`
- Pushes to `main` branch; CI/CD auto-triggers for `apps/adk-server/**` changes

## Personal Assistant — "Luna"

**Persona:** An empowered, proactive business partner. She doesn't wait to be asked — she anticipates needs, orchestrates the agent teams, and keeps your day running smoothly. Senior chief of staff who lives in your WhatsApp.

**Tone:** Warm but efficient. Confident. First person ("I've scheduled that for you", "I'll have the data team pull those numbers"). Not robotic — she has personality.

**Tools:**
- `search_knowledge`, `find_entities`, `record_observation` — full knowledge graph access
- `create_entity`, `update_entity` — manage personal todos/tasks as entities (category="task")
- `query_data_source` — pull data from any connected system (CRM, email, calendar, etc.)
- `schedule_followup` — schedule WhatsApp reminders and cron jobs
- `execute_shell` — check system status, logs when needed

**Capabilities:**
1. **Reminders & crons** — "Remind me to follow up with Acme in 3 days" -> schedules WhatsApp message via `schedule_followup`
2. **Daily briefing** — Proactive morning summary: pending tasks, pipeline updates, key metrics
3. **Connector hub** — "Check my Gmail for invoices this week" -> queries connected sources via `query_data_source` or OpenClaw skills
4. **Task management** — Personal todos stored as entities (category="task") in knowledge graph
5. **Team orchestrator** — "Get me a report on Q1 sales" -> knows to route to data_team. "Research competitor X" -> routes to marketing_team. The friendly front-door to the entire platform.

## Dev Team — Strict Development Cycle

Every request to dev_team goes through all 5 agents in order, no exceptions:

### 1. architect
- **Tools:** `execute_shell`, `search_knowledge`, `record_observation`
- **Role:** Explore codebase (`ls`, `cat`, `grep`, `find`), understand existing patterns, design the solution, write a spec. Records spec as observation. Does NOT write implementation code.

### 2. coder
- **Tools:** `execute_shell`, `search_knowledge`, `record_observation`
- **Role:** Reads architect's spec from session context. Implements code by writing files via shell (`cat > file << 'EOF'`). Installs dependencies (`pip install`). Tests imports (`python -c "import ..."`). Does NOT deploy.

### 3. tester
- **Tools:** `execute_shell`, `search_knowledge`, `record_observation`
- **Role:** Writes test files, runs them (`python -m pytest`). Reports pass/fail. Can fix test files but not implementation files. If tests fail, reports back for coder to fix (dev_team supervisor manages retries).

### 4. dev_ops
- **Tools:** `execute_shell`, `deploy_changes`, `search_knowledge`, `record_observation`
- **Role:** Only agent with `deploy_changes`. Commits all changes, pushes to git. Reports deploy status (commit SHA, triggered workflow). Monitors CI via `execute_shell("gh run list")`.

### 5. user_agent
- **Tools:** `execute_shell`, `search_knowledge`, `record_observation`
- **Role:** Smoke-tests the deployed changes from a user perspective. Calls APIs via curl/httpie. Verifies the new feature works end-to-end. Reports validation results.

## Data Team

Sub-supervisor with flexible routing:
- Analytics, SQL queries, statistical analysis -> `data_analyst`
- Reports, charts, visualizations, formatted exports -> `report_generator`
- Complex requests (analyze + visualize) -> data_analyst first, then report_generator

No changes to existing agent definitions — just wrapped in a team supervisor.

## Sales Team

Sub-supervisor with flexible routing:
- Lead qualification, outreach, pipeline, proposals -> `sales_agent`
- Customer inquiries, FAQ, order status, complaints, greetings -> `customer_support`
- Default for ambiguous requests: `customer_support`
- PharmApp medication/price/order queries -> `customer_support`
- PharmApp B2B partnerships, retention campaigns -> `sales_agent`

No changes to existing agent definitions — just wrapped in a team supervisor.

## Marketing Team

Sub-supervisor with flexible routing:
- Web research, scraping, lead generation -> `web_researcher`
- Entity management, knowledge graph, scoring -> `knowledge_manager`
- Research + store pattern -> web_researcher first, then knowledge_manager

No changes to existing agent definitions — just wrapped in a team supervisor.

## Root Supervisor Routing Update

Simplified routing to 5 top-level entities:

- WhatsApp messages from owner/admin, personal requests, reminders, scheduling, "my tasks", briefing, agenda, general orchestration -> `personal_assistant`
- Code modifications, new tools/agents, shell commands, deploys, infrastructure -> `dev_team`
- Data queries, SQL, analytics, reports, charts -> `data_team`
- Lead qualification, outreach, pipeline, proposals, customer inquiries, FAQ, order status -> `sales_team`
- Web research, scraping, lead enrichment, entity management, knowledge graph, scoring -> `marketing_team`
- Greetings, casual conversation -> `personal_assistant` (Luna handles warmly)

## Inter-Agent Communication

Agents pass context through:
1. **Knowledge observations** — Each agent records what it did via `record_observation`
2. **ADK session state** — Conversation context preserved across `transfer_to_agent` calls
3. **File system** — Dev agents share files (architect writes spec, coder reads it)

## Container Changes

### Dockerfile
- Add `git` package to apt-get install
- Add `entrypoint.sh` for git config at runtime
- Change CMD to use entrypoint

### Helm Values (`agentprovision-adk.yaml`)
- ConfigMap: `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`
- ExternalSecret: `GITHUB_TOKEN` from GCP Secret Manager (`agentprovision-github-token`)

### Git Configuration (entrypoint.sh)
```bash
#!/bin/bash
set -e
if [ -n "$GIT_AUTHOR_NAME" ]; then
    git config --global user.name "$GIT_AUTHOR_NAME"
fi
if [ -n "$GIT_AUTHOR_EMAIL" ]; then
    git config --global user.email "$GIT_AUTHOR_EMAIL"
fi
if [ -n "$GITHUB_TOKEN" ]; then
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
    git config --global --add safe.directory /app
fi
exec python server.py
```

## Security Boundaries

- Agent runs as non-root UID 1000 inside k8s pod
- Shell access confined to container (no host access)
- Container has 1 CPU / 1GB memory limits
- Git push to a specific repo with scoped PAT
- Network: only internal k8s services + github.com for push
- All changes version-controlled (git history = full audit trail)
- Knowledge observations record what each agent changed and why

## Example Flow: "Add a weather tool"

1. User asks "add a tool that fetches weather data"
2. Root supervisor routes to `dev_team`
3. `dev_team` transfers to `architect`:
   - Runs `execute_shell("ls tools/")` and `execute_shell("cat tools/connector_tools.py")`
   - Designs: "Create `tools/weather_tools.py` with async `fetch_weather(city)` using httpx"
   - Records spec as observation
4. `dev_team` transfers to `coder`:
   - Reads spec, writes `tools/weather_tools.py` via shell
   - Updates agent tools list
   - Verifies import: `python -c "from tools.weather_tools import fetch_weather"`
5. `dev_team` transfers to `tester`:
   - Writes `tests/test_weather.py`, runs `pytest tests/test_weather.py -v`
   - Reports: 3/3 tests passing
6. `dev_team` transfers to `dev_ops`:
   - Calls `deploy_changes("feat: add weather tool", [...])`
   - Reports: "Pushed abc123, deploy triggered, ~3 min"
7. `dev_team` transfers to `user_agent`:
   - Smoke-tests via curl against the ADK API
   - Reports: "Weather tool responding correctly"

## File Inventory

### New Files
| File | Type |
|------|------|
| `tools/shell_tools.py` | `execute_shell` + `deploy_changes` |
| `agentprovision_supervisor/personal_assistant.py` | Luna PA agent |
| `agentprovision_supervisor/dev_team.py` | Dev team sub-supervisor |
| `agentprovision_supervisor/architect.py` | Architect agent |
| `agentprovision_supervisor/coder.py` | Coder agent |
| `agentprovision_supervisor/tester.py` | Tester agent |
| `agentprovision_supervisor/dev_ops.py` | DevOps agent |
| `agentprovision_supervisor/user_agent.py` | User validation agent |
| `agentprovision_supervisor/data_team.py` | Data team sub-supervisor |
| `agentprovision_supervisor/sales_team.py` | Sales team sub-supervisor |
| `agentprovision_supervisor/marketing_team.py` | Marketing team sub-supervisor |
| `apps/adk-server/entrypoint.sh` | Git config entrypoint |

### Modified Files
| File | Change |
|------|--------|
| `apps/adk-server/Dockerfile` | Add `git`, use `entrypoint.sh` |
| `helm/values/agentprovision-adk.yaml` | Git credential env vars + secret |
| `agentprovision_supervisor/agent.py` | Replace 6 direct sub-agents with 5 top-level entities |
| `agentprovision_supervisor/__init__.py` | Update exports for new hierarchy |
