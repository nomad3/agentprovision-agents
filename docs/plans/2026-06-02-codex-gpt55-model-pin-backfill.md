# Codex CLI model pin — gpt-5.5 (ChatGPT-account auth fix)

**Date:** 2026-06-02 · **Status:** Backfilled (shipped)
**PRs:** #764
**Files:** `apps/code-worker/workflows.py` (`_prepare_codex_home`), `docker-compose.yml`, `helm/values/agentprovision-code-worker.yaml`

## Problem / context

Codex outage on 2026-06-02: every Codex turn died with `CLI exit 1: Reading additional input from stdin…`. That line is just Codex's startup output — the real error, surfaced by replicating the turn with a fresh re-authed token, was:

```
400 invalid_request_error: 'gpt-5.3-codex' model is not supported when using Codex with a ChatGPT account.
```

Root cause: `_prepare_codex_home` wrote `config.toml` (trust levels + MCP server) with **no `model` key**, so Codex fell back to its built-in default `gpt-5.3-codex` — an API-tier model that ChatGPT-account (subscription) auth rejects. It "worked earlier" only because the prior shared/cloned Codex account happened to support that model. Verified live: `codex exec --model gpt-5.5` returns a normal reply; `gpt-5.3-codex` / `gpt-5-codex` / `gpt-5.1-codex` / `gpt-5` all return "not supported".

## What shipped

`_prepare_codex_home` (`apps/code-worker/workflows.py`) gained an optional `model: str | None = None` arg and now emits a top-level `model = "<x>"` line into the generated `config.toml` (placed before any `[section]`, as required for top-level Codex keys). Resolution precedence:

1. **Per-tenant selection** — the `model` arg (intended to be threaded from the `/integrations` Codex connect flow; backend + frontend selector are a follow-up, not yet wired — the current call site at `workflows.py:1314` passes no `model`).
2. **`CODEX_MODEL` env**.
3. **`gpt-5.5` default** — verified working on subscription auth.

`CODEX_MODEL` was mirrored into both `docker-compose.yml` and `helm/values/agentprovision-code-worker.yaml` (default `gpt-5.5`) to avoid drift. Merged 2026-06-02 (commit `384826dc`); deploys on merge to restore Codex.

## Outcome

Codex turns restored once the worker redeployed with the pinned model. Note the distinct failure modes: a **400 "model not supported"** means a valid token with the wrong model (this fix); a **401 Unauthorized** (`wss api.openai.com`) means a revoked/expired token that needs re-auth, not a model change.

## Related

- Memory `codex_model_pin` — the standing rule (Codex 0.130.0 defaults to `gpt-5.3-codex`; pin `gpt-5.5`; 401 vs 400 triage).
- `docs/plans/2026-05-16-codex-mcp-tool-access-fix.md` — the same `config.toml` generator that this builds on (`CODEX_USE_RMCP_CLIENT`).
- Follow-up TODO: integrations-page per-tenant Codex model selector — store `codex_model` on the Codex integration config → surface on the internal creds endpoint → thread into `_prepare_codex_home(model=…)`.
- Memories `chielo_shared_codex_credential`, `leidyjoanne_shared_codex_credential` — tenants on cloned Codex credentials sharing quota/revocation coupling.
