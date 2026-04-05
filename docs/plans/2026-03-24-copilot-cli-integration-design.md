# GitHub Copilot CLI Integration — Design Document

**Date**: 2026-03-24
**Status**: Draft
**Depends on**: Existing multi-CLI orchestration (Claude Code, Codex, Gemini CLI)

---

## 1. Goal

Add GitHub Copilot CLI as a **full peer** alongside Claude Code, Codex, and Gemini CLI. Copilot CLI participates in chat, code tasks, code reviews, the provider review council, and the RL-driven routing system. It slots into a full-rotation fallback chain where any CLI that exhausts credits hands off to the next available CLI.

## 2. Why Copilot CLI

- **Independent credit pool**: Uses GitHub Copilot subscription (separate from Anthropic/OpenAI billing). Adds genuine redundancy — if Claude and Codex both exhaust credits, Copilot CLI can still serve.
- **Zero extra setup**: Tenants already store GitHub OAuth tokens for code-worker git operations. Copilot CLI authenticates with the same token via `COPILOT_GITHUB_TOKEN` env var. If GitHub is connected, Copilot CLI works automatically.
- **Multi-model access**: Copilot CLI supports Claude Sonnet, GPT-5 mini, and Gemini models under one subscription. The platform can configure the model per tenant.
- **MCP support**: Native MCP server integration via `~/.copilot/mcp-config.json`. Same HTTP transport as our existing MCP tools server.

## 3. Authentication

Reuse the existing `github` integration OAuth token from the credential vault.

**Flow**:
1. Tenant connects GitHub via existing OAuth flow (`/api/v1/oauth/github/authorize`)
2. OAuth token stored encrypted in `integration_credentials` table
3. Code-worker fetches token at runtime: `GET /api/v1/oauth/internal/token/github`
4. Token passed as `COPILOT_GITHUB_TOKEN` env var to `copilot` subprocess

**New integration registry entry** in `INTEGRATION_CREDENTIAL_SCHEMAS`:
```python
"copilot_cli": {
    "display_name": "GitHub Copilot CLI",
    "description": "AI coding agent powered by GitHub Copilot subscription",
    "icon": "FaGithub",
    "auth_type": "oauth",
    "oauth_provider": "github",
    "credentials": [],  # OAuth token handled by provider
}
```

**Token requirement**: GitHub OAuth token must have "Copilot Requests" permission enabled. Existing tokens may need scope expansion.

## 4. CLI Execution

### 4.1 Chat Tasks

```bash
copilot -p "prompt" -s --no-ask-user --allow-all --add-dir <session_dir>
```

Flags:
- `-p` — non-interactive prompt
- `-s` — silent mode (clean text output, no decorations)
- `--no-ask-user` — autonomous decisions, no clarifying questions
- `--allow-all` — full tool permissions
- `--add-dir` — add session directory to allowlist

**Output parsing**: Silent mode returns plain text. No structured JSON. The code-worker wraps it as `{"raw": output}` — same as the existing `json.JSONDecodeError` fallback path (workflows.py:581-582).

### 4.2 Code Tasks (PR Creation)

Copilot CLI participates fully in code tasks. The code-worker already handles non-JSON output gracefully:

1. **Planning phase**: `copilot -p "plan prompt" -s --no-ask-user --allow-all` — text output parsed as raw plan
2. **Implementation phase**: `copilot -p "implement prompt" -s --no-ask-user --allow-all` — writes/edits files via shell access
3. **Git operations**: Same as Claude/Codex — `git add`, `git commit`, `gh pr create` are all shell commands available to Copilot CLI
4. **Review parsing**: The existing lenient fallback parser (workflows.py:347-357) scans raw text for "approved"/"rejected" keywords when JSON parsing fails

No inter-CLI delegation needed. The codebase already handles text-only output at every stage.

### 4.3 Code Reviews

Copilot CLI runs the same review prompts as Claude Code review agents. The prompt asks for JSON `{"approved": bool, "verdict": str, "issues": [], "suggestions": [], "summary": str}`. If Copilot CLI outputs clean JSON — great. If not, the lenient parser extracts the verdict from raw text.

### 4.4 MCP Configuration

Write `~/.copilot/mcp-config.json` in the session directory:

```json
{
  "servers": {
    "servicetsunami": {
      "type": "http",
      "url": "http://mcp-tools:8000/mcp",
      "env": {},
      "tools": "*",
      "headers": {
        "X-Internal-Key": "<MCP_API_KEY>",
        "X-Tenant-Id": "<tenant_id>"
      }
    }
  }
}
```

New helper: `_prepare_copilot_home(session_dir, oauth_token, mcp_config_json)`.

### 4.5 Environment Variables

```python
env["COPILOT_GITHUB_TOKEN"] = oauth_token
env["HOME"] = session_dir  # Copilot reads ~/.copilot/
```

## 5. Fallback Chain (Full Rotation)

Any CLI that exhausts credits tries the remaining CLIs in order:

| Primary | 1st Fallback | 2nd Fallback |
|---------|-------------|-------------|
| Claude Code | Codex | Copilot CLI |
| Codex | Claude Code | Copilot CLI |
| Copilot CLI | Claude Code | Codex |

**Credit exhaustion detection**:

```python
COPILOT_CREDIT_ERROR_PATTERNS = (
    "rate limit",
    "rate_limit",
    "usage limit",
    "quota exceeded",
    "insufficient_quota",
    "subscription required",
    "copilot is not enabled",
    "not authorized",
    "forbidden",
    "out of credits",
    "too many requests",
    "429",
)
```

**Implementation**: Each platform block becomes:
```python
if task_input.platform == "copilot_cli":
    result = _execute_copilot_chat(...)
    if result.success or not _is_copilot_credit_exhausted(result.error or ""):
        return result
    # Try Claude Code
    result = _execute_claude_chat(...)
    if result.success:
        result.metadata["fallback_from"] = "copilot_cli"
        return result
    # Try Codex
    result = _execute_codex_chat(...)
    if result.success:
        result.metadata["fallback_from"] = "copilot_cli"
        return result
    return ChatCliResult(success=False, error="All CLIs exhausted")
```

Existing Claude→Codex and Codex→Claude paths gain Copilot CLI as a third fallback.

## 6. Provider Review Council

Add Copilot CLI as a 4th reviewer in `ProviderReviewWorkflow`.

**Current council**: Claude + Codex + Qwen (local) — 3 reviewers.
**New council**: Claude + Codex + Copilot CLI + Qwen (local) — 4 reviewers.

**Token-gated**: Copilot CLI only participates when the tenant has a GitHub OAuth token with Copilot access. If not connected, the council runs with the existing 3 reviewers.

**Execution**: Same `_safe_review` wrapper pattern — Copilot CLI review runs in parallel with others. If it times out or fails, the other reviewers continue. Agreement computed over all attempted reviewers.

**Provider review function**: New `_copilot_review()` in the provider review activity that:
1. Fetches GitHub token from vault
2. Runs `copilot -p "review prompt" -s --no-ask-user`
3. Parses JSON response (or lenient fallback)
4. Returns score (0-100), verdict, issues, suggestions

## 7. Routing

### 7.1 Platform Registration

Add to `SUPPORTED_CLI_PLATFORMS` in `cli_session_manager.py`:
```python
SUPPORTED_CLI_PLATFORMS = {"claude_code", "codex", "gemini_cli", "copilot_cli"}
```

Add to router platform check in `agent_router.py`:
```python
if platform in ("claude_code", "gemini_cli", "codex", "copilot_cli"):
```

### 7.2 RL Exploration

Copilot CLI included in RL exploration modes:
- `EXPLORATION_MODE=balanced` considers copilot_cli when picking least-explored platform
- Routing decisions logged with `platform: "copilot_cli"` in RL experiences
- Trust metadata attached to copilot_cli-routed responses

### 7.3 Tenant Default

Tenants can set `default_cli_platform = "copilot_cli"` in tenant features to make it their primary platform.

## 8. Code-Worker Dockerfile

Install Copilot CLI in the code-worker container:

```dockerfile
# GitHub Copilot CLI
RUN npm install -g @github/copilot
```

Requires Node.js 22+ (code-worker already has Node.js 20 — needs version bump or use of install script).

## 9. Frontend

Minimal change — add color entry in `IntegrationsPanel.js`:
```javascript
copilot_cli: '#1F6FEB',  // GitHub blue
```

The integration card auto-renders from the registry schema. OAuth flow reuses the existing GitHub provider button.

## 10. Not-Connected Fallback Message

Add to `_INTEGRATION_NOT_CONNECTED_MESSAGES` in `workflows.py`:
```python
"copilot_cli": (
    "GitHub Copilot CLI is not connected. "
    "Please connect your GitHub account in Settings → Integrations "
    "and ensure your GitHub Copilot subscription is active."
),
```

## 11. Safety Governance

Copilot CLI routes through the same safety enforcement layer (Phase 1-3):
- Governed action catalog applies to copilot_cli channel
- Trust profiles computed from copilot_cli RL experiences
- Evidence packs persisted for copilot_cli enforcement decisions

No new safety work needed — the enforcement layer is channel/platform-agnostic.

## 12. Files Changed

| File | Change |
|------|--------|
| `apps/api/app/api/v1/integration_configs.py` | Add `copilot_cli` to registry schema |
| `apps/api/app/services/cli_session_manager.py` | Add to `SUPPORTED_CLI_PLATFORMS`, credential fetch, subscription check |
| `apps/api/app/services/agent_router.py` | Add to platform routing check |
| `apps/code-worker/workflows.py` | `_execute_copilot_chat()`, `_prepare_copilot_home()`, `_is_copilot_credit_exhausted()`, fallback chain (all 3 platforms), credit error patterns, not-connected message |
| `apps/code-worker/Dockerfile` | Install `@github/copilot` via npm |
| `apps/api/app/workflows/activities/provider_review.py` | Add `_copilot_review()`, include in council |
| `apps/api/app/services/auto_quality_scorer.py` | Gate copilot_cli council participation on token availability |
| `apps/web/src/components/IntegrationsPanel.js` | Add color entry |

## 13. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| GitHub token lacks Copilot scope | Check on first use, surface clear error message about required permissions |
| Copilot CLI silent mode output format changes | Lenient parser already handles arbitrary text; low risk |
| Node.js 22 requirement | Code-worker Dockerfile bumps from Node 20 to 22 |
| Copilot CLI not available in container | npm install in Dockerfile; fail gracefully with not-connected message if binary missing |
| Council with 4 reviewers changes agreement thresholds | Agreement still computed as ratio over all attempted reviewers; no threshold change needed |

## 14. Implementation Order

1. **Dockerfile + binary**: Install copilot CLI in code-worker
2. **Registry + routing**: Integration config, supported platforms, router
3. **Execution**: `_execute_copilot_chat()`, `_prepare_copilot_home()`, credit detection
4. **Fallback chain**: Extend all 3 platform blocks to full rotation
5. **Provider council**: Add copilot_cli reviewer
6. **Frontend**: Color entry in IntegrationsPanel
7. **E2E verification**: Test chat, code task, review, fallback, council
