# Luna Computer-Use / Desktop App-Control — Full Critical-Feature Audit

**Date:** 2026-06-10 · **Method:** 13-agent adversarial workflow (7 dimension analyzers + 5 security-claim skeptics + synthesis), Fable 5. Run `wbsqiv9ms`. Covers the plans from 2026-06-05 → 2026-06-09 + the shipped P5.1 actuation + the P5.2 perception chain.

## Executive verdict

The **actuation core is architecturally strong and the headline security claim holds**: a compromised React renderer cannot drive attacker-chosen native input — only server-signed, Ed25519-verified args (or the fixed canary) reach an `enigo` event (single actuation site, fail-closed arg parsing, public-key-only client). The **P5.2 perception quarantine is genuinely "no-read by construction"** (api-only volume, zero GET-bytes route, byte-free SSE).

The remaining issues are **availability/correctness and governance**, not renderer-escape or cross-tenant escalation:
- The **TTL cleanup (PR4)** — now built (#856).
- One adversarial claim **refuted**: canonical JSON is NOT byte-identical for *all* signed fields — `target_binding.bounds` (float) diverges Python↔Rust (same class as the pointer-coord bug, different field). Fail-closed (a "signature invalid" denial), not an escape. Live canary omits `bounds`, so unaffected today.
- The **`desktop_control_enabled` tenant kill-switch is inert on the actuation path** (only P5.2 upload enforces it) — held off only by default-off client env flags. This is the PR4b governance gate; it blocks *autonomy* (P5.4), not the gated-off merges.

**Merge guidance (followed):** the P5.2 chain merged because the feature is off-by-default in production (`desktop_control_enabled=false` everywhere + default-off actuation env flags). Do **not** enable for any non-operator tenant until PR4b wires the flag into the claim boundary.

## Adversarial scorecard

| # | Claim | Verdict | Residual risk |
|---|---|---|---|
| 1 | Compromised renderer can't actuate attacker coords/text | **HOLDS** | Bounded to the renderer; a leaked server private key could sign — by design, outside the threat model |
| 2 | Perception bytes can't reach a planner/LLM/human/log/trace | **HOLDS** | Absence-of-code invariant (not crypto); bytes sit on api-pod disk readable by shell; a crash between read/remove could leave a tmp PNG on-device |
| 3 | Canonical JSON byte-identical Python↔Rust for ALL signed fields | **REFUTED** | Float `bounds` diverges → silent "signature invalid"; pointer args (int micro-units) ARE stable; the "ALL fields" quantifier fails |
| 4 | Every gate is fail-closed | **PARTIAL** | 8 of 9 hold; the capability-flag gate is never invoked on the actuation path (PR4b) |
| 5 | Internal X-Internal-Key endpoints permit no cross-tenant escalation | **HOLDS** | Per-tenant *containment* gap (not cross-tenant): a globally-allowlisted bundle + a non-operator tenant with a logged-in user + device + actuation env flags would actuate despite that tenant's flag being off |

## Risk register

**Fixed in PR4 (#856):** TTL cleanup sweeper (the production BLOCKER); orphan-bytes warning logging; Helm-side volume-isolation assertion.

**Before Luna autonomously actuates (P5.4 / PR4b gate):**
- BLOCKER — `_ensure_desktop_control_enabled` at all 5 desktop service functions, re-checked at *claim* time (the real boundary).
- BLOCKER — per-tenant `pointer_control_enabled` / `keyboard_control_enabled` enforced by action class.
- HIGH — `native_control_target_allowlist` threaded (effective = per-tenant ∩ global floor).
- HIGH — `desktop_observe` / `desktop_control` tool-group split + agent-token scope at every entrypoint.
- HIGH — operator-tenant backfill + legacy-key cutover in the *same* deploy as enforcement (else the live canary breaks).
- HIGH — per-tenant signing-key registry + `(tenant_id, key_id)` verify (PR5).

**Correctness / hardening follow-ups:**
- HIGH — `target_binding.bounds` float canonicalization: quantize to int or strip from the signed payload (mirror the pointer fix).
- MEDIUM — server/client keyboard-chord normalization divergence (Python recognizes only `shift`; Rust recognizes shift/ctrl/alt/cmd) — bounded by the arrows-only allowlist today, latent foot-gun on expansion.
- MEDIUM — envelope expiry ms timestamps: pin explicit UTC both sides + a ±1s skew tolerance.
- MEDIUM — server-lifecycle integration tests missing for the secure-input, pacing, single-owner, target-window-drift, Stop-mid-claim gates (tested only as pure decision logic).
- Doc — phase-numbering map + the missing `2026-06-09-luna-phase5-general-app-control-design.md`; P5.2↔PR4b prerequisite matrix.

## Critical path to "Luna controls any app from chat"

1. **P5.2 perception** (in flight) — PR4 cleanup [done #856] + volume CI assertion + `bounds` fix → safe to enable.
2. **PR2 durability** — `DESKTOP_*` + `JWT_AGENT_TOKEN_SECRET` externalSecrets on api+worker; reconcile Terraform. (Hard prereq for PR4b backfill.)
3. **PR4b enforcement + governance** — THE gate before autonomy (flags at claim time, tool-group split, allowlist, operator backfill).
4. **PR5 per-tenant keys** → **PR6 capabilities** → **PR7 client consumption**.
5. **P5.0 general app-control design doc** (author it) → **P5.3 redactor + validator** (first perception consumer) → **P5.4 agent loop** → **P5.5 chat trigger**.

**Highest-value next action (after PR4):** PR4b governance enforcement — it's the single gate between "operator-only canary" and "any tenant, governed."
