# Codex CLI MCP Tool Access — Implementation Plan

**Date:** 2026-05-16
**Owner of the bug:** `apps/code-worker/workflows.py::_codex_mcp_config_lines` + `_prepare_codex_home`

---

## 1. Root-cause analysis

### 1.1 What works today

`apps/code-worker/cli_executors/claude.py` (lines 60–62, 100–102) writes the shared MCP JSON config straight into `<session_dir>/mcp.json` and passes `--mcp-config <path>` on the `claude` command line. Claude Code accepts `{"mcpServers": {"agentprovision": {"type": "sse", "url": ".../sse", "headers": {...}}}}` natively.

`apps/code-worker/workflows.py::_prepare_gemini_home` (lines 1547–1556) embeds the same `mcpServers` dict (including `"type": "sse"`) verbatim into `<session_dir>/.gemini/settings.json`. Gemini CLI honors that shape — verified by the working tenant session.

The MCP server itself (`apps/mcp-server/src/mcp_serve.py:18`) runs `mcp.run(transport="sse")`. There is **no stdio entry point** for our agentprovision MCP server. SSE is the only transport offered to leaf CLIs.

### 1.2 What's broken for Codex

`apps/code-worker/workflows.py::_codex_mcp_config_lines` (lines 1358–1409) emits a `~/.codex/config.toml` block:

```toml
[mcp_servers.agentprovision]
transport = "sse"
url = "http://mcp-tools:8086/sse"
http_headers = { "X-Tenant-Id" = "...", "X-Internal-Key" = "...", "Authorization" = "Bearer <agent_token>" }
```

A previous fix (comments at lines 1361–1383) switched from `transport = "streamable_http"` to `transport = "sse"`. **Necessary but not sufficient.**

**Actual root cause:** Codex CLI's **default built-in MCP client supports only `stdio`-launched MCP servers.** It silently ignores `transport = "sse"` entries unless the top-level `experimental_use_rmcp_client = true` flag is set in `config.toml`. Without that flag, Codex parses the `[mcp_servers.agentprovision]` block, tries to interpret as stdio (no `command` field → invalid → silently dropped), reports zero MCP tools.

Grep across the repo:
```
grep -rn "experimental_use_rmcp_client" /Users/nomade/Documents/GitHub/agentprovision-agents/
→ (no matches)
```

### 1.3 File-level diff between Claude (working) and Codex (broken)

| Concern | Claude path | Codex path | Status |
|---|---|---|---|
| MCP config materialization | `cli_executors/claude.py:60-62` raw JSON | `workflows.py:_prepare_codex_home:1349-1350` calls `_codex_mcp_config_lines` to TOML | Codex needs translation; Claude doesn't |
| MCP transport handshake | `--mcp-config <path>` → Claude binary speaks SSE per `type` | Codex binary defaults to **stdio-only built-in client** | **Broken — missing rmcp opt-in** |
| Auth (agent-scoped JWT) | `cli_session_manager.generate_mcp_config:481` adds Bearer header; Claude forwards on `/sse` | Same headers in TOML `http_headers`; **never reach server because client never connects** | Broken downstream |
| Env var for CLI auth | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` | `CODEX_HOME` + `auth.json` | Working |

### 1.4 The exact missing line

`_prepare_codex_home` (line 1341) constructs `config_lines` starting with `[projects."..."]` and `trust_level = "trusted"`. **Nowhere is `experimental_use_rmcp_client = true` written.** That single missing TOML key is the proximate root cause.

---

## 2. Codex MCP config format — spec

### 2.1 Authoritative source

Repository contains no quoted spec (external OpenAI dependency). Upstream: https://github.com/openai/codex. **Research task before merging.**

### 2.2 Working hypothesis (Codex CLI 0.20+)

**Stdio (default, built-in client):**
```toml
[mcp_servers.NAME]
command = "/path/to/binary"
args = ["--flag"]
env = { KEY = "value" }
```

**Streamable-HTTP / SSE (requires opt-in to Rust MCP client):**
```toml
experimental_use_rmcp_client = true   # top-level flag, REQUIRED

[mcp_servers.NAME]
url = "https://mcp.example.com/sse"
transport = "sse" | "streamable_http"
bearer_token = "..."        # alternative to http_headers
http_headers = { "X-Key" = "val" }
```

### 2.3 Research subtasks (must complete before merging)

1. Exact key name: `experimental_use_rmcp_client` vs `experimental_use_streamable_http` vs `experimental_rmcp_client`.
2. TOML key for HTTP headers: `http_headers` vs `headers`.
3. Whether `transport = "sse"` is honored or auto-detected from URL.
4. Whether `bearer_token` is preferred over `http_headers.Authorization`.
5. Codex version pinned in `apps/code-worker/Dockerfile` to determine rmcp_client schema.

Dispatch a one-shot WebFetch research subagent: fetch `https://github.com/openai/codex/blob/main/codex-rs/core/src/config.rs` and `https://github.com/openai/codex/blob/main/docs/config.md`.

---

## 3. Implementation steps (one PR)

### Step 1 — Add `experimental_use_rmcp_client = true` to materialized Codex config

**File:** `apps/code-worker/workflows.py`
**Function:** `_prepare_codex_home` (line 1333)

Insert top-level TOML key BEFORE `[projects.*]` blocks (top-level keys must appear before any section header):

```python
config_lines = [
    "experimental_use_rmcp_client = true",
    "",
    f'[projects."{WORKSPACE if os.path.isdir(WORKSPACE) else session_dir}"]',
    'trust_level = "trusted"',
    ...
]
```

Only emit when `mcp_config_json` is non-empty.

### Step 2 — Verify TOML key names in `_codex_mcp_config_lines`

**File:** `apps/code-worker/workflows.py:1358`

After research subtask 1.5, confirm `http_headers` vs `headers`. Update emitter at line 1408 if needed.

### Step 3 — Add unit tests

**File:** `apps/code-worker/tests/test_workflows_helpers.py` (extend `TestCodexMcpConfigLines`)

```python
def test_prepare_codex_home_emits_rmcp_opt_in(tmp_path):
    home = wf._prepare_codex_home(
        str(tmp_path),
        {"OPENAI_API_KEY": "sk-..."},
        json.dumps({"mcpServers": {"agentprovision": {"type": "sse", "url": "http://x/sse"}}}),
    )
    cfg = (Path(home) / "config.toml").read_text()
    assert cfg.startswith("experimental_use_rmcp_client = true")
    assert "[mcp_servers.agentprovision]" in cfg

def test_prepare_codex_home_omits_rmcp_when_no_mcp(tmp_path):
    home = wf._prepare_codex_home(str(tmp_path), {"OPENAI_API_KEY": "sk-..."}, "")
    cfg = (Path(home) / "config.toml").read_text()
    assert "experimental_use_rmcp_client" not in cfg
```

### Step 4 — Verify line-1186 callsite

The standalone code-execution workflow calls `_prepare_codex_home(session_dir, auth_payload, "")` — empty MCP. With Step 1's conditional, stays a no-op. No change needed.

### Step 5 — Update bug-history docstring on `_codex_mcp_config_lines`

Append 2026-05-16 incident note: SSE transport entries are inert unless `experimental_use_rmcp_client` is set; the previous 2026-05-12 transport-string fix was necessary but did not enable the path.

### Step 6 — Smoke test the rolled binary

```sh
docker exec <code-worker-pod> codex --version
```

If older than rmcp_client introduction (~Codex CLI 0.20, mid-2025), bump version in `apps/code-worker/Dockerfile` + rebuild.

---

## 4. Test plan

### 4.1 Unit / worker tests

```sh
cd apps/code-worker && pytest tests/test_workflows_helpers.py::TestCodexMcpConfigLines -v
cd apps/code-worker && pytest tests/test_prepare_homes.py -v
```

### 4.2 Local integration

1. Connect tenant Codex credential via Integrations.
2. Set `tenant_features.default_cli_platform = "codex"`.
3. From chat UI: **"list my github repos"**.
4. Watch agent activity panel — `list_github_repos` MCP call must appear ≤10s.

### 4.3 Tenant smoke (5 categories)

| Prompt | Expected tool |
|---|---|
| "search the knowledge graph for entities tagged 'lead'" | `find_entities` |
| "recall what we know about Acme Corp" | `recall_memory` |
| "list my connected email accounts" | `list_connected_email_accounts` |
| "what's on my calendar tomorrow" | `list_calendar_events` |
| "list my github repos" | `list_github_repos` |

All 5 must fire (matches Claude Code parity today).

### 4.4 Negative test (rollback safety)

Disable feature flag (Section 5) — Codex still executes without MCP, doesn't crash.

### 4.5 Observability check

```sh
SELECT tool_name, COUNT(*) FROM mcp_tool_calls
WHERE tenant_id = '<tenant>' AND created_at > now() - interval '5 minutes'
GROUP BY tool_name;
```

Must show ≥5 rows.

---

## 5. Rollback plan

### 5.1 Feature flag (defensive)

```python
CODEX_USE_RMCP_CLIENT = os.environ.get("CODEX_USE_RMCP_CLIENT", "true").lower() == "true"

if CODEX_USE_RMCP_CLIENT and mcp_config_json:
    config_lines.insert(0, "experimental_use_rmcp_client = true")
    config_lines.insert(1, "")
```

Default ON. Flip OFF via Helm values (`code-worker.env.CODEX_USE_RMCP_CLIENT=false`) if rmcp_client regresses. Worker restart only.

### 5.2 Hard rollback

`git revert` the PR. Single-file change + one test file. No DB schema, no public API, no UI. One-step worker redeploy.

### 5.3 Blast radius

- Affects: Codex tenant chats only.
- Does not affect: Claude Code, Gemini, Copilot, opencode, standalone Codex (line-1186 path passes empty MCP config).

---

## 6. Open risks

1. **Codex CLI version pin** — if worker image ships pre-rmcp Codex, flag silently ignored. Mitigation: log `codex --version` at worker startup; alert if below cutoff.
2. **rmcp_client schema drift** — OpenAI renamed the flag at least once. Mitigation: research subtask 2.3.1 + write both keys if ambiguous.
3. **Header forwarding parity** — confirm rmcp_client forwards `http_headers` on the initial SSE handshake AND on every `/messages` POST. Mitigation: server-side log in `apps/mcp-server/src/mcp_auth.py` when auth headers absent from Codex-origin requests.

---

## Critical files

- `apps/code-worker/workflows.py` (`_prepare_codex_home` L1333, `_codex_mcp_config_lines` L1358)
- `apps/code-worker/cli_executors/codex.py` (caller L47 — verify no change needed)
- `apps/code-worker/tests/test_workflows_helpers.py` (extend `TestCodexMcpConfigLines`)
- `apps/code-worker/tests/test_prepare_homes.py` (new assertion)
- `apps/code-worker/Dockerfile` (verify Codex CLI version)
