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
| **P5.3** | Perception redactor + validator — the FIRST consumer of quarantined bytes: redact/validate into a `planner_safe` artifact. (Today every artifact is `not_planner_safe`.) | ⏳ next | — |
| **P5.4** | Agent perception→action loop — Luna reasons over a planner-safe observation and issues the next signed actuation. | ⏳ | — |
| **P5.5** | Chat trigger — "Luna, do X in app Y" from the chat surface drives the loop end-to-end. | ⏳ | — |

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

## 6. Current state (2026-06-10)

- Perception: **enabled fleet-wide** (54/54 tenants `desktop_control_enabled=true`,
  migration 168). Actuation: **fail-closed OFF** for all but the operator/canary
  tenant (per-capability flags, migration 169).
- Actuation governance: enforced at enqueue + claim (PR4b, #859).
- Bytes: no-read-by-construction quarantine with TTL cleanup (#856).

## 7. Critical path forward

1. **PR4c** — per-tenant allowlist threading + tool-group/scope governance split.
2. **PR5 → PR6 → PR7 → PR8** — per-tenant keys, capabilities projection, client
   consumption, ramp + runbook + metrics.
3. **P5.3 redactor/validator** (first planner-safe perception) → **P5.4 agent loop**
   → **P5.5 chat trigger** — the "Luna controls any app from chat" payoff, now on a
   governed multi-tenant footing.

## 8. References

- `docs/plans/2026-06-09-luna-computer-use-core-productionization-design.md` (+ `-codex-review.md`, `-luna-review.md`)
- `docs/plans/2026-06-09-luna-phase5.2-governed-perception-design.md`
- `docs/report/2026-06-10-luna-computer-use-full-audit.md`
- `docs/operator/luna-e2e/` (live-validation harnesses)
- `memory/computer_use_core_feature_directive.md`, `memory/luna_phase5_general_app_control.md`
