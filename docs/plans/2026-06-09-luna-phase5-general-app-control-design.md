# Luna Phase 5 — general desktop app control (design)

**Status:** Draft for Codex (gpt-5.5) + Luna review · **Date:** 2026-06-09 · **Owner:** nomade

**Goal (Simon):** From the Luna Tauri chat, give Luna a real goal ("open my WhatsApp desktop app and send Simon a message") and she **perceives the screen and drives arbitrary mouse/keyboard to operate any app** until it's done. Full desktop control, safely. This generalizes the fixed Phase 3/4 *canary* into a real computer-use agent. See memory `luna_phase5_general_app_control`.

---

## 1. Current state — reuse the foundation, don't rebuild it

Phases 3–4 shipped the hard part: a **safe, signed, audited actuation path**. Phase 5 generalizes it.

**Reusable (verified):**
- **Actuation primitives** are already coordinate-parameterized: `gesture/cursor.rs` `move_abs(x,y)` / `click()` map normalized → absolute pixels via `enigo` CGEvent; the canary path (`canary_move_norm`/`canary_click`/`canary_type_text`/`canary_key_chord`) is the same enigo layer. `enigo` already supports arbitrary move/click/type/key — no new actuation backend needed.
- **`GLOBAL_MODE`** (`cursor.rs:24`, `set_global_mode()`): default OFF requires frontmost==Luna; **ON allows actuating other apps**. This is the scaffold a Phase-5 session flips on (scoped, Stop-able).
- **The boundary** (`computer_use/policy.rs` `evaluate_native_control_*`): frontmost / target-window / secure-input / single-owner / pacing / Stop / lease gates. Phase 5 keeps all of them; only the *target* gate relaxes (canary-bundle → session-scoped allowed apps).
- **Signed-command path**: API issues Ed25519-signed native-control commands; the client claims + verifies + boundary-gates + actuates + audits (`desktop_control_service.py`, `useDesktopCommandClaims.js`). Every Phase-5 action flows through this so it stays **auditable + Stop-able**.
- **Lease** (`actuation_lease.rs`): capability/TTL/budget/pacing — the session lease.
- **Screen-recording permission infra**: `permissions.rs` `screen_recording_readiness()` via `CGPreflightScreenCaptureAccess`; the `Screenshot` capability already gates on `screen_recording` (`policy.rs:48`).
- **Observation audit**: `desktop_observe_screen`/`get_active_app`/`read_clipboard` are wired (metadata-only audit today).

**Gaps to close (Phase 5):**
1. **Perception** — real screen *capture* + transmission to a vision LLM is NOT implemented (only the permission probe + metadata audit exist). The heart of the loop.
2. **Arbitrary-action commands** — the server only issues fixed canary actions; need `pointer_move(x,y)` / `pointer_click(x,y)` / `keyboard_type(arbitrary)` / `key_chord(arbitrary)` / `scroll` carrying real payloads, still signed.
3. **Generalized keyboard** — `keyboard_bounds.rs` caps to the canary chord allowlist + fixed text; general typing needs arbitrary text (within a sane cap) and a broader (still bounded) chord set.
4. **The agent loop** — perceive→plan→act→observe→repeat, driven by a vision model.
5. **Chat trigger** — a free-text goal in chat dispatches a computer-use *session*.
6. **Session safety model** — the canary's fixed-target gate is replaced by a user-approved, scoped, time-boxed session with Stop always live + sensitive-action confirmation.

---

## 2. Architecture — the perceive→plan→act loop

```
Luna chat: "open WhatsApp and message Simon"
        │  (dispatch a computer-use SESSION — user-approved, scoped, time-boxed)
        ▼
┌──────────────────────────  loop (until goal done / Stop / budget) ──────────────────────────┐
│ 1. PERCEIVE  client captures a screenshot (CGDisplay/ScreenCaptureKit) → uploads (downscaled,│
│              redaction-aware) to the session                                                  │
│ 2. PLAN      Claude computer-use model sees the screenshot + goal → emits the next action     │
│              (move/click/type/key/scroll/open-app) as a tool call                             │
│ 3. ACTUATE   action → API issues a SIGNED arbitrary-action command → client claims/verifies → │
│              boundary gates (Stop, secure-input, pacing, session-scope, frontmost-or-GLOBAL)  │
│              → enigo CGEvent                                                                   │
│ 4. OBSERVE   next screenshot feeds back; publish_session_event streams progress to the chat   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Perception engine = Anthropic Claude computer-use** — the model natively takes screenshots and emits mouse/keyboard tool calls; the platform already runs Claude Code. We run the loop server-side (code-worker), the "computer" being Luna's desktop: screenshots flow client→API→Claude; actions flow Claude→API(signed command)→client→enigo. This keeps every action on the audited, Stop-able path.
- **New pieces:** client screenshot capture + upload; arbitrary-action command types + signing; the computer-use session orchestrator (a new session type, likely a `DesktopControlSessionWorkflow` or an extension of the CLI orchestrator running Claude with the computer tool); the chat→session dispatch; the session safety gate.
- **Reused unchanged:** the boundary, lease, enigo, GLOBAL_MODE, the signed-command claim/verify, the Stop latch, the screen-recording permission.

---

## 3. Design decisions (forks — my recommendations; building these unless review overturns)

| Fork | Decision | Why |
|---|---|---|
| Perception/planning engine | **Claude computer-use** (vision model emits computer actions) | Mature, native to the platform's Claude stack; avoids hand-rolling a perceive-plan loop. |
| Approval model | **Per-session** (user approves a scoped, time-boxed computer-use session), not per-action | Per-action is unusable for real work; the durable Stop kill switch + sensitive-action confirmation provide in-flight control. |
| App scope | **Operator-approved app set first** (WhatsApp, TextEdit, …), widen to any app once trusted | Fail-closed start; the session lease carries the allowed-bundle set; "any app" is a later widening, not the first cut. |
| Where the loop runs | **Server-side session orchestrator** (code-worker, Claude computer-use), actuation via signed commands to the client | Keeps the LLM + planning server-side (cost/control), actuation client-side + audited. |
| Coordinate space | Screenshot px → **screen px via the captured display scale** (the client maps back) | Claude reasons in screenshot pixels; the client owns the display geometry (already does in `move_abs`). |
| Action transport | **Extend the existing signed native-control command** with arbitrary payloads | One audited path; no second actuation channel. |

---

## 4. Safety model — full control, fail-closed

- **User-approved session**: a computer-use session starts only on explicit user approval in the Luna UI (goal + allowed apps + time box shown). No silent sessions.
- **Durable Stop kill switch always live** (`stop_state.rs`): one click halts the session + releases the lease; the latch is re-checked at *every* actuation (already enforced).
- **Secure-input fail-closed**: never type while `IsSecureEventInputEnabled()` (password fields) — already enforced for keyboard; extended to the general type path.
- **Lease/pacing**: session lease with TTL + per-action pacing + action budget; exhaustion ends the session.
- **Session scope**: actuation only within the session's allowed-bundle set + time box; GLOBAL_MODE is ON only for the session's lifetime, OFF otherwise.
- **Sensitive-action confirmation**: irreversible controls (Send / Submit / Delete / Pay) pause for a human confirmation (or a per-session "auto-confirm sends" the user opts into) — so Luna pauses before clicking "Send" in WhatsApp unless told otherwise.
- **Value/safety floor**: session admission + each high-risk action passes the platform safety floor / value arbitration (the same layer governing agent autonomy).
- **Audit**: every action + screenshot reference logged to `desktop_command_events`; screenshots are display-safe-handled (no secret leakage in audit).

---

## 5. Phased plan — each independently testable LIVE, converging on WhatsApp

- **P5.1 — arbitrary actuation (no LLM yet).** Server arbitrary-action command types (`pointer_move{x,y}`, `pointer_click{x,y}`, `keyboard_type{text}`, `keyboard_key_chord{keys}`, `scroll`) signed; client executes via the existing primitives; boundary relaxes target to a session-scoped allowed-bundle set with GLOBAL_MODE; generalized keyboard text (bounded). **Live test:** a scripted sequence types a real string + clicks at real coords in TextEdit (an approved app). Proves general actuation end to end.
- **P5.2 — perception.** Client screenshot capture (ScreenCaptureKit/CGDisplay) + upload; the screen-recording permission flow. **Live test:** Luna captures the screen and the image round-trips to the server.
- **P5.3 — the agent loop.** The session orchestrator runs Claude computer-use: screenshot→action→signed command→actuate→screenshot. **Live test:** "type 'hello' into TextEdit" driven entirely by the model.
- **P5.4 — chat trigger + session safety.** Free-text goal in the Luna chat → user-approval modal → session dispatch; Stop, sensitive-action confirmation, scope, progress streaming. **Live test:** approve a session from chat; Stop halts it.
- **P5.5 — the WhatsApp flow.** "open WhatsApp and send Simon a message" runs end to end: open app → focus message box → type → (confirm) send. **The goal.**

Each phase ships as its own PR (Codex gpt-5.5 + Luna reviewed). The per-tenant productionization (PR4b+) proceeds independently and gates *enablement*; Phase 5 is the capability.

## 6. Testing
Rust unit tests for the generalized primitives + bounds + boundary-with-session-scope; API tests for arbitrary-action command signing + session lease + scope enforcement; the live E2E suite extended per phase; the WhatsApp flow as the P5.5 acceptance test (driven from chat).

## 7. Open items
Screenshot capture crate vs native ScreenCaptureKit (macOS 14+); screenshot redaction (don't upload password fields / sensitive windows); model cost/latency of the loop; how "any app" widens past the approved set; reconciling the session lease with the per-tenant enablement flags (PR4b).

## 8. Review
Codex (gpt-5.5) + Luna before implementation per the standing process; findings folded; then build P5.1.
