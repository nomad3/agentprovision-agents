# Luna Computer-Use — Fable 5 Full Review (2026-06-04 → 2026-06-10)

**Date:** 2026-06-11 · **Method:** 116-agent adversarial workflow (run `wf_17bd6ecb-030`), Fable 5:
10 closure verifiers (one per prior-audit risk item, each tasked to *disprove* closure), 6 dimension
reviewers over the post-audit diff `539e8e92..main` (PRs #857–#866), 2 skeptics per finding,
plus orchestrator-inline E2E gap tracing and live-production verification.
**Scope:** the full feature line since Thursday — PRs #832–#866, ~43k lines / 294 files: Phase 3/4
canary actuation, P5.1 signed arbitrary actuation, P5.2 governed perception, P5.3a-1 redactor core,
PR2–PR4d productionization/governance, WhatsApp send.
**Supersedes** the risk register in `2026-06-10-luna-computer-use-full-audit.md` (9 of its
statements are now stale; closure status below).

## Executive verdict

The week's work is **architecturally sound and the governance gates are now real**: 7 of the 10
prior-audit risk items are verifiably closed in code, including both BLOCKERs (claim-time
per-capability enforcement with a genuine `FOR UPDATE` TOCTOU closure) and the allowlist /
tool-group-split / operator-backfill HIGHs. The headline invariants still hold under adversarial
re-review: single actuation site, verified-args-only, no-read-by-construction perception.

**No blocker or high-severity *code* defect was found in the post-audit merges.** The mediums are:
one real client-side gap (lease pacing can never fire), two infra-drift traps (compose env
precedence makes `apps/api/.env` DESKTOP_\* inert; the live Ed25519+floor config exists only in
untracked PRODUCTION.env while tracked Helm pins the opposite), and a cluster of test-integrity
gaps where the suite asserts shapes the production path doesn't take.

**The E2E goal — "Luna, from a chat prompt, drives an app and reports back" — is not yet wired,
and the gap is now precisely four missing links** (§4): no desktop tool groups granted to any Luna
agent, no actuation/perception-content MCP tools (observation stubs only), the merged redactor has
zero callers, and the chat path has zero desktop awareness. Everything below those links —
signing, claiming, actuating, governance — works and is live-proven by the WhatsApp send.

## 1. Prior-audit closure scorecard

| # | Item (prior severity) | Status | Notes |
|---|---|---|---|
| 1 | Master kill-switch at all entrypoints + claim time (BLOCKER) | **partially closed** | Closed for the native-control/actuation path (enqueue `desktop_control_service.py:738`, claim `:2674-2693` with `FOR UPDATE`, envelope only after `:2786`). **Residual (medium):** the observe down-channel (enqueue `:2544-2611`, claim, `create_desktop_approval_grant :2324`) skips `_ensure_desktop_control_enabled` — a revoked tenant can still be issued signed *observe* envelopes. Latent today (no client consumes that channel; internal-key only) but becomes live with any observe down-channel client. |
| 2 | Per-capability flags by action class at enqueue + claim (BLOCKER) | **closed** | Capability derived server-side from action, never client-supplied; persisted-vs-derived mismatch denies; unknown class denies; flags absent from all member-writable schemas; cross-class independence tested. |
| 3 | Per-tenant target allowlist, effective = tenant ∩ floor (HIGH) | **closed** | Enforced `:935-984`; revocation honored at claim. |
| 4 | `desktop_observe`/`desktop_control` tool-group split + scope (HIGH) | **closed** (low residual) | Registry split shipped; MCP exposes observation tools only. Residual: split tested only at static-registry layer. |
| 5 | Operator backfill + allowlist seed in same deploy (HIGH) | **closed** | Migrations 169/170/172 applied; canary survived (live-verified). Low residual: 169 derives flags from *any* historical command row incl. denied attempts. |
| 6 | Per-tenant signing-key registry (HIGH, = PR5) | **open** | Single global Ed25519 key can mint envelopes for any tenant/device; client does not bind `tenant_id`/`user_id` to local identity (only shell/session/device ids). Requires API-host compromise to exploit (key is server-side only) — **the** remaining multi-tenant-GA security gate. |
| 7 | `target_binding.bounds` float canonicalization (HIGH) | **closed** | Quantized int micro-units both sides + cross-language lock test (#858). |
| 8 | Chord normalization divergence (MEDIUM) | **closed for the current allowlist** | `enter` chord canonical both sides (#865). The *general* divergence (Python folds only `shift`; Rust folds ctrl/alt/cmd too) remains and fires on the first allowlist expansion — see finding M-5. |
| 9 | Envelope expiry skew (MEDIUM) | **partially closed** (low) | No ±1s tolerance (strict, fail-closed both sides — acceptable). Real residuals: `lib.rs:109 unwrap_or(0)` is fail-open on pathological clocks; Python sends ISO `expires_at` while Rust reads `expires_at_ms` → the client-side approval-expiry check and approval-capped lease TTL are **dead code** (mitigated by server-side grant liveness + envelope expiry). |
| 10 | Server-lifecycle tests for the 5 deny gates (MEDIUM) | **partially closed** | The +422-line suite closed PR4b/PR4c items, not this one. 4 of 5 gates are *client-side* decisions (server tests impossible as framed); the real untested server seam is denial-reason completions flowing through `complete_desktop_command` → denial_code audit. |

## 2. Live production verification (this machine, read-only)

- Migrations 166–172 all applied; `_migrations` consistent.
- `tenant_features`: 54/54 `desktop_control_enabled` (perception), exactly 1 tenant
  (AgentProvision/operator) with pointer+keyboard actuation, allowlist
  `[com.agentprovision.luna, com.apple.TextEdit, net.whatsapp.WhatsApp]`.
- Running api image: Pillow 12.2.0 present; all four `DESKTOP_*` signing vars set.
- Perception TTL sweeper running (interval 600s, root `/var/agentprovision/observations`).
- **`perception_artifacts` has 0 rows ever** — governed perception is enabled fleet-wide but has
  never captured a single artifact in production. The capture path is live-unvalidated.

## 3. Confirmed findings (post-audit merges, adversarially verified)

### Medium

| ID | Dim | Finding |
|---|---|---|
| M-1 | client | **Client 250ms pacing can never fire**: `claim_actuation_lease` rebuilds the lease on every allowed proof with `last_action_at_ms: None` (`lib.rs:1502-1528`, called at `:2302`), so `lease_actuation_decision`'s pacing branch never denies; the boundary pacing gate reads a renderer-supplied timestamp. (Budget reset per-proof is documented intent; pacing is not.) Fix: carry forward `last_action_at_ms` from a live same-owner lease, or plumb it Rust-side. |
| M-2 | drift | **Live runtime config only in untracked PRODUCTION.env**; tracked Helm prod values pin the opposite (HMAC + empty floor, `helm/values/agentprovision-api.yaml:155,160-161`). Fix: track non-secret values (algorithm, floor) in Helm; externalSecrets for the key. |
| M-3 | drift | **Compose `environment:` defaults make `apps/api/.env` DESKTOP_\* inert** (`docker-compose.yml:104-111,202-209` override env_file; `${VAR:-default}` always materializes) — setting Ed25519 in `apps/api/.env` silently downgrades to HMAC. Helm precedence is reversed. The documented key-rotation footgun class, again. |
| M-4 | tests | **Signed args path (`payload.args` → `envelope.args`) has zero integration tests** — the exact path WhatsApp-send uses; validators unit-tested in isolation only. |
| M-5 | tests | **Keyboard-privacy tests assert a payload shape prod doesn't take**: tests put text at payload top level (stripped) and assert non-persistence; the real path persists `payload["args"]["text"]` verbatim by design. The "typed text never persisted" invariant the tests green-light is false. Pin the *real* invariant: args text in row, absent from events/display-safe payloads. |
| M-6 | tests | **`FOR UPDATE` TOCTOU closure unverifiable by suite** (SQLite no-op): deleting `lock=True` keeps all tests green. Needs a Postgres-marked CI test (per repo rule: DB tests to CI, never prod DB). |
| M-7 | tests | `test_allowlist_revoked_after_enqueue_denies_at_claim` passes whether denied, pending, or expired — assert `status=="denied"` + event + grant unconsumed (sibling test does it right). |
| M-8 | debt | **Python↔Rust keyboard validator divergence** (modifier folding shift-only vs shift/ctrl/alt/cmd; ASCII vs Unicode-Cc control chars) — agreement today only because the allowlist is tiny; becomes a wire divergence on first expansion (e.g. `cmd+a`). |
| M-9 | debt | **Five canonical tables hand-duplicated Python↔Rust** ("must stay byte-identical" comments as the only sync mechanism): denial codes, ordered reason prefixes, gate functions, chord allowlist, micro-units. Fix: one checked-in JSON fixture loaded by both pytest and Rust tests. |
| M-10 | debt | **`desktop_control_service.py` is a 3,104-line monolith <1 week old** mixing 8+ concerns; PR5/PR6/P5.4 all slated to extend it. Split (envelope/args/approvals/verbs) before PR5. |
| M-11 | debt | **Vestigial HMAC envelope path**: config default still HMAC-SHA256 while native-control hard-denies non-Ed25519 and the client only accepts Ed25519 — HMAC now signs only observation envelopes nothing verifies. Flip default, delete with PR5. |
| M-12 | debt | **Phase-map doc stale one day after authoring** (PR4c "next" though merged; no PR4d row; P5.3 "next" though 5.3a-1 merged) — refreshed status needed; it is the audit reference doc. |
| M-13 | security (from closure #1) | **Observe down-channel + approval grants skip the master kill-switch** — fix alongside M-1-class work; add observe-path master-off test. |

### Low / nit (28 confirmed; abbreviated)

Redactor: TTL-race strands redacted bytes forever; post-commit ambiguous failure leaves dangling
`planner_safe` row; unknown region kinds silently ignored (fail-open seam); `_atomic_write` ignores
short writes; StubEngine-only tests; max-attempts cap untested; **zero production call sites +
dead `PERCEPTION_REDACTOR_ENABLED` flag**. Crypto/wire: HMAC fallback reuses JWT secret without
domain separation; `pointer_click` `button` silently stripped (right-click actuates as left);
lone-surrogate args → 500 at JSONB insert; `isinstance(display_id,int)` accepts bool; chord wire
representation not unique; C1 controls sign-able server-side but always client-denied; fixture
uses padded base64 vs prod unpadded-url. Client: signed window rectangle not enforced at actuation
(full-display clamp + bundle match only); dead `canary_click` export; `LUNA_ACTUATION_*` env flags
duplicate DB flags with no convergence marker. Infra: observations PVC RWO vs api replicaCount 2;
local Helm never enables the quarantine volume; requirements.lock via-annotation stale; migration
169 backfills from any historical row; 168 default-true with no per-tenant byte quota; down-script
scope re-derivation. Docs/debt: stale "inert allowlist"/"disabled" comments and docstrings; dead
`_DISABLED_NATIVE_CONTROL_ACTIONS` cluster (86-line unreachable path); three phase-numbering
namespaces; `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST` misnamed (it's the global floor); no API
mutation path for desktop flags (SQL-only ramp until PR8); tool-group test placement;
`whatsapp-send.sh` robustness (unchecked step-2 grant, unescaped JSON interpolation, no send
verification).

**Review integrity note:** 13 late skeptic agents + both dedicated gap agents hit the session
rate limit; affected tech-debt/client-rust findings above are marked from primary review without
independent verification — M-1 was re-verified by the orchestrator directly; the E2E gap map below
was traced inline by the orchestrator (greps + live DB reads), not by the failed agents.

## 4. E2E gap map — chat prompt → app control → report back

**Works today (live-proven, operator-driven):** `whatsapp-send.sh` exercises the full governed
chain — internal-key grant (`/desktop-control/internal/approval-grants`) → enqueue with signed
args → client claim (~2s poll) → Ed25519 verify → boundary gates → single-site enigo actuation →
status + display-safe audit events. A human supplies: app prep (frontmost/focus), the plan, the
grant calls, and result verification by looking at the screen.

**Missing links (all four required; each has its substrate ready):**

| # | Gap | Evidence | Builds on |
|---|---|---|---|
| G-1 | **No agent-facing actuation/perception tools.** MCP has 3 observation *stubs* that return audit envelopes, no pixels, no actuation, "until the Tauri command down-channel ships" (`apps/mcp-server/src/mcp_tools/desktop_control.py`). | Luna cannot call grant/enqueue/poll at all. | PR4d scope split exists precisely to gate these; internal endpoints exist; kernel rule: ship as `alpha desktop act/observe` verbs + thin routes + MCP wrappers. |
| G-2 | **No Luna agent has desktop tool groups.** Operator tenant's Luna/Luna Supervisor/Luna General Assistant `tool_groups` contain no `desktop_observe`/`desktop_control` (live DB read). | Even the stubs are unreachable. | Grant via agent update + JWT scope (existing mechanism; the accountable-learning lesson: tool not in tool_groups + not granted = unreachable). |
| G-3 | **Perception content never reaches a planner.** Redactor merged with zero callers; 0 artifacts ever captured in prod; no `planner_safe` delivery path (P5.3a-2/P5.3b: driver + validator + fetch path). | `grep perception_redactor` → only the module itself; `perception_artifacts` count = 0. | Redactor core + quarantine + sweeper all shipped; needs the driver hook (post-upload or sweep), a real `PERCEPTION_REDACTOR_ENABLED` wire-up, and a scoped redacted-content fetch for the agent loop. |
| G-4 | **Chat path has zero desktop awareness.** No mention in `enhanced_chat.py`, `cli_session_manager.py`, `agent_router.py`; only `alpha desktop preflight` exists as a verb; approval grants are internal-key-only (no user-facing approval UX). | Prompt "send X on WhatsApp" routes nowhere. | `human_approval` workflow precedent for the approval UX; session-events SSE for live progress; persona/CLAUDE.md injection for tool awareness (P5.4 loop + P5.5 trigger). |

## 5. Remediation plan

### 5a. Debt burn-down (sequenced PRs, all small except D5)

- **D1 — server gate + wire hardening:** M-13 observe-path master gate (+ grant gate + test);
  `pointer_click` button explicit deny-or-sign; bool `display_id` reject; surrogate reject;
  chord-wire uniqueness; C1 alignment (M-8 partial).
- **D2 — client correctness:** M-1 pacing carry-forward; `expires_at` field-name fix (emit
  `expires_at_ms`) so the dead client approval-expiry checks go live; `unwrap_or(0)` fail-closed;
  delete dead `canary_click` + dead gesture-actuation path.
- **D3 — drift:** M-2 + M-3 (Helm tracks Ed25519+floor; compose drops `${VAR:-default}`
  overrides for DESKTOP_\*; local Helm quarantine volume; PVC/replica note); flip signing default
  to Ed25519 (M-11 step 1).
- **D4 — test integrity:** M-4 args-path integration test; M-5 real-invariant privacy tests;
  M-6 Postgres `FOR UPDATE` CI test; M-7 strengthen; denial-completion lifecycle tests (closure
  #10 residual); member-writable exclusion pin; redactor max-attempts.
- **D5 — structural:** M-9 single shared JSON fixture for the five canonical tables (do first);
  M-10 service split (envelope/args/approvals/verbs) — **before PR5 lands**; delete HMAC path +
  dead-code cluster + stale comments/docstrings; M-12 phase-map refresh + audit-report closure
  annotations (this report supplies them).

### 5b. Feature path to the E2E goal

1. **P5.3a-2 — redactor driver** (closes G-3 first half): post-upload hook or sweep-integrated
   redaction, real `PERCEPTION_REDACTOR_ENABLED` flag, live E2E harness extension; fix the
   redactor lows (TTL race, dangling planner_safe, short-write, unknown-region fail-closed) here.
2. **P5.3b — validator + planner-safe delivery** (closes G-3): scoped fetch of redacted content
   for the agent loop, validator gate, `alpha desktop observe` verb.
3. **P5.4 — agent loop** (closes G-1, G-2): `alpha desktop act` verbs + thin routes + MCP tools
   (`desktop_request_grant`, `desktop_actuate`, `desktop_command_status`) gated by
   `desktop_control` scope; grant groups to operator Luna; loop = observe → plan → act → observe
   inside the existing ChatCliWorkflow; session events + RL experiences per action (kernel rules).
4. **P5.5 — chat trigger + report-back** (closes G-4): user-approved scoped session from chat
   (approval UX on `human_approval` precedent; Stop affordance already client-side), prompt
   routing, final outcome message with audit refs.
5. **Multi-tenant GA gates (parallel track, not operator-autonomy blockers):** PR5 per-tenant
   keys (the open HIGH), PR6 capabilities projection, PR7 client consumption, PR8 ramp + flag
   mutation API.

Operator-tenant autonomy needs 1–4 only; **PR5 stays the hard gate before any non-operator tenant
gets actuation**, per the productionization design.

## 6. References

- Prior audit: `docs/report/2026-06-10-luna-computer-use-full-audit.md` (risk register superseded by §1)
- Phase map: `docs/plans/2026-06-09-luna-phase5-general-app-control-design.md` (needs M-12 refresh)
- Designs: productionization (`2026-06-09-…-core-productionization-design.md`), P5.2 perception, P5.3 redactor
- Live harnesses: `docs/operator/luna-e2e/`
