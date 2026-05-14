# README `alpha` CLI Section — Design

**Date:** 2026-05-13
**Status:** Approved (verbal) — implementing on `docs/readme-alpha-cli`
**Scope:** Top-level `README.md` + targeted `CONTRIBUTING.md` fixes. No other files touched.

## Problem

The `alpha` CLI shipped a usable command surface (`login`, `chat`, `agent`,
`workflow`, `session`, `memory`, `skill`, `integration`, `upgrade`,
`completions`, `quickstart`) and is documented at
[`docs/cli/README.md`](../cli/README.md) (~514 lines). The differentiation
roadmap ([`2026-05-13-ap-cli-differentiation-roadmap.md`](2026-05-13-ap-cli-differentiation-roadmap.md))
and the multi-runtime dispatch plan ([`2026-05-11-ap-cli-multi-runtime-dispatch-plan.md`](2026-05-11-ap-cli-multi-runtime-dispatch-plan.md))
exist as plans.

But the top-level `README.md` — the page anyone landing from GitHub or
`agentprovision.com` reads first — contains zero mention of `alpha`. Today
the README's only entry points are the web SPA, WhatsApp, and the Luna
desktop client. Terminal-first users (the primary audience for an
orchestration-CLI product) are invisible.

## Non-goals

- No changes to `docs/cli/README.md` (already thorough).
- No restructure of existing Luna, ALM, A2A, Skills Marketplace, MCP-tools, or
  architecture sections.
- No new architecture diagram — the CLI hits the same FastAPI backend already
  shown.
- No promotion of unshipped roadmap items as "live". The new section will
  distinguish shipped commands from planned differentiators.
- No additional documentation files. The full reference already exists.

## Changes to `README.md`

Five small edits, in the order they appear top-to-bottom:

### 1. Badge row (after line 13)

Add one badge between the existing `Luna_Client` badge and the closing
`</p>`:

```html
<a href="docs/cli/README.md"><img src="https://img.shields.io/badge/alpha_CLI-terminal_client-2ecc71?style=flat-square" alt="alpha CLI"></a>
```

### 2. New section `## alpha — Terminal AI Client` (after the Luna section, before `## Architecture`)

Mirrors Luna's shape: one-line tag, status table, install + demo snippet,
"what makes it different" callout, link to full reference. ~35–45 lines.

Content outline:
- Lede: terminal-native counterpart to Luna; same FastAPI backend; scriptable
  (`--json`), CI-friendly (`--no-stream`), keychain-stored token, ~30-min JWT.
- Status table (Shipped vs Planned), sourced from `docs/cli/README.md` TOC
  and the eight differentiators in `2026-05-13-ap-cli-differentiation-roadmap.md`.
- Install one-liner from `docs/cli/README.md` Install section.
- 4-line demo: `alpha login` → `alpha status` → `alpha chat send "…"` →
  `alpha workflow run`.
- One-sentence pointer to the differentiation roadmap, no promises.
- Link to full reference.

### 3. "Connect Your Agent" (current line ~492–495)

Insert as item 0 (terminal-first audience is the new primary path):

```
0. **Terminal**: `curl -fsSL https://agentprovision.com/install.sh | sh && alpha login && alpha quickstart`
```

Existing 1-4 (Claude Code, Gemini CLI, chat, RL) keep their numbering shifted
by one — or stay 1-4 with the new bullet labelled separately as a
"Terminal-first?" preface. Implementation will pick whichever reads cleanly
without disturbing line counts more than necessary.

### 4. Documentation table (current line ~522)

Add one row:

```
| [`docs/cli/README.md`](docs/cli/README.md) | `alpha` CLI reference — login, chat, workflow, memory, skill, integration |
```

And one bullet under "Recent highlights":

```
- [`docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md`](docs/plans/2026-05-13-ap-cli-differentiation-roadmap.md) — eight CLI differentiators planned for `alpha`
```

### 5. Footer (line 543)

Append `· alpha CLI`:

```
*Built with Claude Code CLI . Codex CLI . Gemini CLI . MCP . Temporal . Ollama . pgvector . Neonize . Cloudflare . FastAPI . React . Tauri . alpha CLI*
```

### 6. `CONTRIBUTING.md` fixes (separate file, same PR)

#### 6.1 Clone URL (lines 27–28)

The current snippet points at `nomad3/servicetsunami-agents` — that repo
either doesn't exist or is stale. The real `origin` is
`https://github.com/nomad3/agentprovision-agents.git`. Same bug exists in
README.md line 461–462 and is fixed there too.

#### 6.2 "When in doubt" list (lines 164–171)

Insert a row for the CLI reference (currently omitted):

```
- For the `alpha` CLI: [`docs/cli/README.md`](docs/cli/README.md).
```

**Not done in this PR (would need design):** new `alpha`-specific section
in CONTRIBUTING.md; rewording "CLI runtime routing" to distinguish leaf-CLI
runtimes from the orchestrator CLI. Both are reasonable follow-ups.

## Verification

- `grep -c '\balpha\b' README.md` rises from 0 to ≥ 10.
- README still renders on GitHub (no broken markdown — verified by local
  preview / `grip` if available).
- All new links resolve to files in this repo.
- Shipped/Planned columns in the status table match the actual contents of
  `docs/cli/README.md` (shipped) and `2026-05-13-ap-cli-differentiation-roadmap.md`
  (planned). No item from the roadmap is mislabelled as shipped.
- `grep -rn 'nomad3/servicetsunami-agents' .` returns 0 hits after the URL
  fixes (currently 2 hits: `README.md:461`, `CONTRIBUTING.md:27`).

## Drift checklist

- Helm: N/A (markdown only).
- Terraform: N/A.
- `agentprovision.code-workspace`, `CLAUDE.md`, `AGENTS.md`,
  `CONTRIBUTING.md`: not touched; their existing CLI guidance (if any) is
  left alone.

## Out of scope (deferred)

- Adding a CLI section to `agentprovision.com` landing page (marketing-site
  repo, separate change).
- Asciinema cast of `alpha` commands (would belong under `docs/cli/` not the
  README).
- Localized README copies.

## Execution

- Branch: `docs/readme-alpha-cli` (already created from `origin/main` in
  worktree `.claude/worktrees/readme-alpha-cli/`).
- Two commits: (1) this design doc, (2) the README edits.
- PR assigned to `nomad3`. No AI-credit lines per repo rules.

## Addendum 2026-05-13 — supersedes parts of this design

After the initial two commits, the user directed: "remove all icons from
documentation, enhance with ASCII diagrams when necessary." This changes
two earlier sections of this spec:

- **Section 1 (badge row) is fully superseded.** The shields.io badge row
  — *including* the `alpha_CLI-terminal_client` badge this spec prescribed
  — is removed in its entirety and replaced with a fenced ASCII status
  block that preserves the same information (live URL, orchestrated CLI
  runtimes, surfaces, capabilities, infra). Commit: `82c5798f`.
- **Section 2 (Connect Your Agent) item numbering revised.** Initial commit
  inserted the terminal path as `0.` per the design's "items 0–4" sketch.
  Code review noted the `0.`-prefixed list renders inconsistently across
  markdown engines. The list was renumbered 1–5 with the terminal path as
  step 1.

Subsequent code review (subagent `superpowers:code-reviewer`) also flagged
that the README's "Planned" column for `alpha run` / `watch` / `cancel` /
`--fanout` / cost-attribution / RBAC / audit-log was wrong: those
subcommands are already wired in `apps/agentprovision-cli/src/cli.rs` and
shipped via PRs #434 / #436 / #438 (Phase 1 wedge). Phases 2–4 of the
roadmap (`policy`, `coalition`, `recipes`, `usage`, `costs`, `recall`,
`remember`) are likewise present in the source tree. The "Planned" column
was rewritten to mark all of these Shipped and to retain only the
genuinely future item (`alpha recipes publish`, Phase 5).

Other code-review fixes applied in the same fix-up commit:

- `alpha session` row corrected to `alpha session` / `sessions` (both
  variants exist in `apps/agentprovision-cli/src/commands/`).
- Footer "Built with…" line no longer credits `alpha CLI` — it is a
  product, not a dependency, so it does not belong in that list.

The original verification checklist still holds; the only change is that
the "shipped vs planned" parity now reflects the actual source-tree state
rather than the design's first-pass guess.
