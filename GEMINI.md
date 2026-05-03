# GEMINI.md

> Gemini CLI agents working in this repo: see [`CLAUDE.md`](CLAUDE.md) for the full architecture, dev commands, models, services, workflows, deployment patterns, and hard rules. The same instructions apply.

For a quick agent reference (CLI runtimes, ALM, A2A, Skills v2, MCP tools, code style) see [`AGENTS.md`](AGENTS.md).

For the platform's required `tenant_id` rule and other Gemini-specific notes, see the **Calling MCP tools (Luna / OpenCode / local Gemma 4)** section in `AGENTS.md` — the rule is the same for Gemini CLI: every MCP tool call must include `tenant_id`.

## Hard rules (mirrored from CLAUDE.md)

- **Never** commit to `main` — feature branch + PR. Assign PRs to `nomade`.
- **Never** add `Co-Authored-By: Claude` (or any AI credit — Gemini, Codex, Copilot) to commits, PRs, or comments.
- **Never** add docs / plans / tests / scripts at the repo root — use dedicated folders (`docs/plans/`, `docs/report/`, `docs/changelog/`, `scripts/`).
- All multi-tenant queries must filter by `tenant_id`. No exceptions.
- When making manual changes, mirror them into Helm + Git + Terraform to prevent drift.
- Don't build production Tauri DMGs locally — push to main, let CI build.
