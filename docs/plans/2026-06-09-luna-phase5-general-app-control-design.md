# Luna Phase 5 — General Desktop App Control (consolidated design + phase map)

**Status:** living document · **Authored:** 2026-06-10 (closes the audit gap in `docs/report/2026-06-10-luna-computer-use-full-audit.md` §"Doc")

This is the umbrella design that ties together the previously-scattered Phase 5
(`P5.x`) feature phases and the productionization (`PRx`) track into one map. It
does **not** redesign anything already shipped — it records the as-built
structure, the current state, and the critical path so future work and audits
have a single reference. The detailed designs live in the per-phase docs linked
below; this doc is the index + the numbering reconciliation.

## 1. Goal

Luna perceives the screen and drives arbitrary mouse/keyboard to operate **any**
desktop app from her chat — generalizing the fixed canary into governed,
multi-tenant, durable computer-use that is a CORE platform feature (see
`memory/computer_use_core_feature_directive.md`). Every capability flows through
the Alpha CLI kernel as an `alpha desktop …` verb with a thin v1 route.

## 2. The two tracks

Phase 5 is delivered along **two interleaving tracks**. They share the same
actuation/perception substrate but answer different questions:

| Track | Question it answers | Numbering |
|---|---|---|
| **Feature (`P5.x`)** | *What can Luna do on the desktop?* | P5.0 → P5.5 |
| **Productionization (`PRx`)** | *How is it made durable, multi-tenant, governed, ramped?* | PR1 → PR8 |

The feature track builds capability against the operator canary; the
productionization track makes that capability safe for every tenant. PR4
(governance enforcement) is the hinge: it is the gate between "operator-only
canary" and "any tenant, governed" — the autonomy gate.

## 3. Feature phases (`P5.x`)

| Phase | What | Status | Primary docs / PRs |
|---|---|---|---|
| **P5.0** | Platform contract — the signed-command + boundary + observation contracts every channel honours | ✅ shipped | `2026-06-09-luna-computer-use-core-productionization-design.md` |
| **P5.1** | Signed bounded actuation — server issues Ed25519-signed command envelopes; client verifies + actuates ONLY verified args (single actuation site). Pointer coords as integer micro-units. | ✅ shipped + live-validated (#851→#852; bounds-canonicalization hardening for `target_binding.bounds` in #858) | — |
| **P5.2** | Governed perception transport — capture → quarantine (TTL) → byte-free reference on single SSE; "no-read by construction". | ✅ shipped (#853/#854/#855 + PR4 cleanup #856) and **enabled fleet-wide** (`desktop_control_enabled=true`, migration 168, #857) | `2026-06-09-luna-phase5.2-governed-perception-design.md` |
| **P5.3** | Perception redactor + validator — the FIRST consumer of quarantined bytes: redact/validate into a `planner_safe` artifact and expose only reviewed planner-safe delivery. | ✅ substrate shipped (#880, #890, #891, #892); live operator proof still required | `2026-06-11-luna-agent-loop-chat-trigger-execution.md`, `2026-06-10-luna-phase5.3-perception-redactor-design.md` |
| **P5.4** | Agent perception→action loop — Luna reasons over a planner-safe observation and issues the next signed actuation. The general app-control actuator must use the secondary-pointer/background-control design, not global cursor warping. | ⏳ in progress: dry-run/status/Stop/pending-request scaffolds shipped; next is `desktop_actuate` with an existing grant | `2026-06-11-luna-secondary-pointer-background-control.md`, `2026-06-11-luna-agent-loop-chat-trigger-execution.md` |
| **P5.5** | Chat trigger — "Luna, do X in app Y" from the chat surface drives the loop end-to-end. | ⏳ partial: human approval surface shipped (#896); chat trigger/report-back still pending | `2026-06-11-luna-agent-loop-chat-trigger-execution.md`, `2026-06-11-luna-p55-approval-surface-design.md` |

## 4. Productionization phases (`PRx`)

From `2026-06-09-luna-computer-use-core-productionization-design.md` §6/§7
(Codex + Luna reviewed v3):

| PR | What | Status |
|---|---|---|
| **PR1** | Design doc (+ both reviews folded). | ✅ |
| **PR2** | Durability / de-drift — secrets→externalSecrets, worker/compose/local parity, redaction set, source-of-truth then TF. No behaviour change. | ✅ (#848) |
| **PR3** | Dedicated cached readiness preflight + `alpha desktop preflight run`. | ✅ (#849) |
| **PR4a** | `tenant_features` schema + migration 166 (flags, default-OFF, fail-closed). | ✅ (#850) |
| **PR4b** | **Enforcement at the claim boundary** — per-capability flags (pointer/keyboard) wired into enqueue **and** claim; mid-flight revoke denies fail-closed; operator backfill preserves the canary. | ✅ this work (#859) — **closes audit BLOCKER G10 / Codex B1** |
| **PR4c** | Per-tenant target allowlist (effective = tenant ∩ floor, G4) + `desktop_observe`/`desktop_control` tool-group split + agent-token scope (L-B2). | ⏳ next (deferred from PR4b for reviewability) |
| **PR5** | Per-tenant Ed25519 key registry + `(tenant,key_id)` sign/verify + rotation + `alpha desktop keys`. | ⏳ |
| **PR6** | `/presence/capabilities` projection + `alpha desktop capabilities get` + event/RL placement. | ⏳ |
| **PR7** | Client: React `apiFetch`→Tauri injection, cache fail-closed, identity binding, single-SSE, offline fallback. Signed DMG via CI. | ⏳ |
| **PR8** | `alpha desktop enablement/allowlist/commands` verbs + ramp + runbook + metrics + extend `computer-use-suite.sh`. | ⏳ |

## 5. Phase-numbering reconciliation

The two tracks map onto each other at the gates:

```
P5.0 contract ─┐
P5.1 actuation ─┼─ canary-grade (operator only) ── PR1/PR2/PR3/PR4a
P5.2 perception ┘
                         │  PR4b  ← THE AUTONOMY GATE (flags enforced at claim)
                         ▼
        ── governed multi-tenant ── PR4c → PR5 → PR6 → PR7 → PR8
                         │
P5.3 redactor → P5.4 agent loop → P5.5 chat trigger   (ride on top, per-tenant governed)
```

- **Before PR4b**: the per-tenant capability flags were INERT on the actuation
  path — actuation was held off only by default-off client env flags. The audit
  rated this claim #4 PARTIAL and the single gate before autonomy.
- **PR4b (this work)**: wires `pointer_control_enabled` / `keyboard_control_enabled`
  into the claim boundary (the real gate before a signed envelope is built),
  fail-closed, with a `SELECT … FOR UPDATE` serialization against concurrent
  revoke. The master `desktop_control_enabled` is now true fleet-wide (for
  perception, migration 168) — which does **not** imply actuation: that needs the
  per-capability flags, which stay default-OFF. The operator/canary tenant is
  backfilled (migration 169, data-derived) so the live canary survives.
- **After PR4b**: P5.3+ and PR4c→PR8 proceed on a governed, per-tenant footing.

## 6. Current state (2026-06-11)

- Perception: **enabled fleet-wide** (54/54 tenants `desktop_control_enabled=true`,
  migration 168). Actuation: **fail-closed OFF** for all but the operator/canary
  tenant (per-capability flags, migration 169).
- Actuation governance: enforced at enqueue + claim (PR4b, #859).
- Bytes: no-read-by-construction quarantine with TTL cleanup (#856).
- Planner-safe perception: redactor driver, planner-safe fetch/status, MCP
  SSRF hardening, and Tesseract engine are merged (#880, #890, #891, #892).
- Agent-facing control substrate: dry-run command/status, Stop, pending approval
  request/status, and human approve/deny/list surfaces are merged (#879, #881,
  #882, #893, #895, #896). No agent-facing path mints grants; #896 is
  user-JWT-only and does not enqueue or actuate.
- Pointer model correction: the global `enigo` cursor path is acceptable as a
  fixed canary only. General app control requires scoped target-app injection
  plus an overlay pointer/HUD so Luna can act in a background app without
  stealing the operator's cursor. See
  `2026-06-11-luna-secondary-pointer-background-control.md`.

## 7. Critical path forward

1. **`desktop_actuate` feature slice** — agent-facing act verb that consumes an
   already-approved grant, queues only bounded governed commands, and returns
   `approval_required` when the grant is absent. This is the next make-it-work
   link after #895/#896.
2. **PR5 → PR6 → PR7 → PR8** — per-tenant keys, capabilities projection, client
   consumption, ramp + runbook + metrics.
3. **P5.4 agent loop** → **P5.5 chat trigger/report-back** — the "Luna controls
   any app from chat" payoff, now on a governed multi-tenant footing without
   global cursor theft. The execution ladder is in
   `2026-06-11-luna-agent-loop-chat-trigger-execution.md`.

## 8. References

- `docs/plans/2026-06-09-luna-computer-use-core-productionization-design.md` (+ `-codex-review.md`, `-luna-review.md`)
- `docs/plans/2026-06-09-luna-phase5.2-governed-perception-design.md`
- `docs/plans/2026-06-11-luna-secondary-pointer-background-control.md`
- `docs/plans/2026-06-11-luna-agent-loop-chat-trigger-execution.md`
- `docs/report/2026-06-10-luna-computer-use-full-audit.md`
- `docs/report/2026-06-11-luna-computer-use-fable-review.md`
- `docs/operator/luna-e2e/` (live-validation harnesses)
- `memory/computer_use_core_feature_directive.md`, `memory/luna_phase5_general_app_control.md`
