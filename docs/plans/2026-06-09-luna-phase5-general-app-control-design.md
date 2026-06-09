# Luna Phase 5 — general desktop app control (design v2)

**Status:** v2 — Codex (gpt-5.5) review folded; pending Luna review · **Date:** 2026-06-09 · **Owner:** nomade

**Goal (Simon):** From the Luna Tauri chat, give Luna a real goal ("open my WhatsApp desktop app and send Simon a message") and she **perceives the screen and drives arbitrary mouse/keyboard to operate any app** until it's done — full desktop control, **safely**. Generalizes the fixed Phase 3/4 *canary* into a real computer-use agent. Memory: `luna_phase5_general_app_control`.

**v2 changes (Codex review):** prompt-injection is now the central safety axis; the sensitive-action gate is deterministic (not the vision model); perception is corrected (capture exists — transport+redaction is the gap); session safety moves *before* the model loop; the target-window gate is noted as currently inert; Claude computer-use is a new orchestrator integration. See §10.

---

## 1. Current state — reuse the foundation (corrected)

**Reusable (verified):**
- Actuation primitives are coordinate-parameterized: `gesture/cursor.rs` `move_abs(x,y)`/`click()` map normalized→absolute px via `enigo`; `enigo` does arbitrary move/click/type/key. No new actuation backend.
- The **boundary** (`computer_use/policy.rs`): frontmost / secure-input / single-owner / pacing / Stop / lease. Kept; the *target* gate is extended (canary-bundle → session scope).
- **Signed-command path** (`desktop_control_service.py` + `useDesktopCommandClaims.js`): every action stays auditable + Stop-able.
- **Lease** (`actuation_lease.rs`), **Stop latch** (`stop_state.rs`), **secure-input** check — real.
- **Screenshot capture EXISTS** — `lib.rs:2041` `capture_screenshot` (native `screencapture`, base64); chat image upload exists (`ChatInterface.jsx:73`). (Corrected from v1.)
- Screen-recording permission probe (`permissions.rs` `CGPreflightScreenCaptureAccess`).

**Caveats / not-yet-foundation (Codex):**
- **`GLOBAL_MODE`** (`cursor.rs:24`) bypasses frontmost in the *gesture* path; the **signed canary path owns target-binding separately**, so session scope is enforced in the *signed-command boundary*, not by GLOBAL_MODE alone.
- The **target-window gate is currently INERT** — `lib.rs:1168` `live_window_matches_target.unwrap_or(true)`; no live window reader. General control needs this made real.
- **Session-scoped allowlist does not exist yet** — current target policy is the global `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`; the tenant flags (migration 166) are not read yet. Built in Phase 5, not reused.
- Arbitrary action *names* exist but **execute fixed canary payloads** (center point, `luna canary`, right-arrow) — `useDesktopCommandClaims.js:49`. P5.1 wires real payloads through with validation.
- Existing MCP observation returns **no pixels**; the command-claim path strips screenshots to metadata (`useDesktopCommandClaims.js:169`). Perception **transport** is the real gap, not capture.

---

## 2. Architecture — perceive→plan→act, with the screen as untrusted input

```
Luna chat goal ──► user-approved SESSION (goal + allowed apps + time box + confirm policy — FIXED at start)
   │
   ▼  loop (until done / Stop / budget):
   1 PERCEIVE  client capture_screenshot → governed upload (downscaled, redaction-aware, retention-bounded)
   2 PLAN      Claude computer-use sees screenshot+goal → proposes next action. SCREEN = DATA, NEVER INSTRUCTION.
   3 VALIDATE  deterministic plan/action validator: action ∈ allowed set, target ∈ session apps, coords on-screen,
               NOT a sensitive control unless confirmed; the session contract is immutable by screen content.
   4 ACTUATE   action → signed arbitrary-action command → client claim/verify → boundary (Stop/secure-input/
               pacing/session-scope/target-window) → enigo
   5 OBSERVE   next screenshot; publish_session_event streams progress to chat
```

- **Perception/planning = Anthropic Claude computer-use** (vision model emits computer actions). Integrating it is a **new orchestrator/API integration** (P5.4), NOT a `ChatCliWorkflow` extension — the existing Claude Code CLI path does not feed screenshots to the model.
- Actuation always flows through the signed-command + boundary path → audited, Stop-able.

---

## 3. Security model — prompt injection is the primary threat (Codex BLOCKER 1)

The planner reads the **screen**, which is **untrusted content** — a hostile window, web page, message, or document could try to redirect Luna. This is the same instruction-source boundary that governs the platform: **observed content is data, not commands.**

- **Screen content is DATA, never instruction.** The planning prompt states this explicitly; on-screen text can inform *what's where*, never *what to do*.
- **Immutable session contract.** The user goal, the allowed-app set, the confirmation policy, and the safety rules are fixed when the session is approved and **cannot be changed by anything the model reads on screen**. The validator (deterministic, §4) rejects any action that would widen scope, disable confirmation, or pursue a goal the user didn't set.
- **No instruction extraction from screen → control plane.** The model may not, on the basis of screen text, add apps, raise the budget, clear Stop, or auto-confirm sends. Those are operator-only controls.
- **Plan/action validator (deterministic, not the vision model).** Every proposed action is checked by code: action type allowed; target bundle ∈ session apps; coordinates within the captured display; rate within pacing; and the sensitive-action gate (§4). The model proposes; the validator disposes.

## 4. Sensitive-action gate — deterministic, separate from the vision model (Codex BLOCKER 2)

Irreversible controls (Send / Submit / Delete / Pay / Post) must NOT be gated by the same model that read hostile screen content. A **deterministic policy gate** intercepts them:
- Detection by action *context* (a click whose target is a button matching a send/submit/delete affordance via the accessibility tree, or Return in a message composer), not the vision model's say-so.
- On a sensitive action the session **pauses** and surfaces to the user: intent, app, target, click coordinates/context, and the **exact text about to be sent** — for explicit confirm. (A per-session "auto-confirm sends" the user may opt into for low-stakes flows.)
- So Luna pauses before clicking "Send" in WhatsApp and shows you the exact message + recipient, unless you pre-approved.

## 5. Safety model (full control, fail-closed) — must exist BEFORE the model loop (Codex NIT 2)
User-approved scoped time-boxed session; durable Stop always live (re-checked every action); secure-input fail-closed (never type into password fields); lease/pacing/budget; session scope (allowed apps + GLOBAL_MODE only for the session lifetime); **screenshot redaction** (skip/secure-handle password fields + sensitive windows before upload; bounded retention; display-safe audit); the value/safety floor on session admission + high-risk actions; full audit to `desktop_command_events`.

## 6. Phased plan — safety before the loop (re-sequenced)

- **P5.1 — arbitrary actuation (no LLM).** Server arbitrary-action commands (`pointer_move{x,y}`/`pointer_click{x,y}`/`keyboard_type{text}`/`keyboard_key_chord{keys}`/`scroll`) signed; client **pass-through with action-specific payload validation** (replace the fixed canary payloads); generalize keyboard text (bounded); **make the target-window gate live** (real window reader, not `unwrap_or(true)`); session-scoped allowlist + GLOBAL_MODE-for-session. **Live test:** scripted sequence types a real string + clicks real coords in TextEdit (approved app).
- **P5.2 — perception transport + redaction.** Loop-grade governed capture→upload (downscale, redact, bounded retention) + feed to the planner; not metadata-stripped. **Live test:** a real screenshot round-trips server-side.
- **P5.3 — session safety + injection defenses.** Session model (approval, scope, time box, Stop, budget), the deterministic plan/action **validator** (§4), the immutable session contract (§3), the sensitive-action gate, screenshot redaction. **Built before any model drives the loop.**
- **P5.4 — the Claude computer-use loop.** New orchestrator/API integration running Claude computer-use: screenshot→action→validator→signed command→actuate→screenshot. **Live test:** "type 'hello' into TextEdit" driven by the model, validator enforcing scope.
- **P5.5 — chat trigger + progress.** Free-text goal in the Luna chat → approval modal → session dispatch → streamed progress; Stop from chat.
- **P5.6 — the WhatsApp flow.** "open WhatsApp and message Simon" end to end: open app → focus composer → type → sensitive-action confirm → send. **The goal.**

Each phase = its own PR (Codex gpt-5.5 + Luna reviewed). Per-tenant productionization (PR4b+) is independent (enablement); Phase 5 is the capability.

## 7. Testing
Rust: generalized primitives + bounds + boundary-with-session-scope + the live target-window reader. API: arbitrary-action signing + session lease + scope enforcement + the deterministic validator + sensitive-action gate. Injection tests: on-screen "instructions" must NOT change goal/scope/confirm-policy. E2E extended per phase; the WhatsApp flow as P5.6 acceptance.

## 8. Open items
Screenshot redaction policy (which windows/fields are sensitive); ScreenCaptureKit vs `screencapture` for loop-grade capture; the accessibility-tree reader for target-window + sensitive-control detection; model cost/latency; widening past the approved app set; reconciling the session lease with the per-tenant enablement flags (PR4b).

## 9. Review
Codex (gpt-5.5) folded (§10); Luna platform review next; then build P5.1.

## 10. Codex (gpt-5.5) review v1 — folded
B1 prompt injection → §3 (screen=data, immutable contract, deterministic validator). B2 sensitive-action gate → §4 (deterministic, separate from the model, exact-text confirm). Screenshot capture exists → §1 corrected, P5.2 reframed as transport+redaction. Arbitrary actions execute fixed payloads → P5.1 adds payload validation+pass-through. Session-allowlist not foundation → §1 caveat. Target-window gate inert (`unwrap_or(true)`) → §1 + P5.1 makes it live. Claude-computer-use is new → §2/P5.4. GLOBAL_MODE caveat → §1. Safety before the loop → §5/§6 re-sequenced (P5.3 before P5.4).
