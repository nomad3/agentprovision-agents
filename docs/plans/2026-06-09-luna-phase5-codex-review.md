# Codex (gpt-5.5) review — Luna Phase 5 design (v1)

Read-only, vs the live codebase. **Verdict: revise before implementation** — direction sound; folded into v2.

## Blockers
- **B1 prompt injection** — the planner reads the screen (untrusted). Design must enforce screen=data-never-instruction + a deterministic plan/action validator so on-screen text can't change the goal/allowed-apps/confirm-policy/safety. → v2 §3.
- **B2 sensitive-action gate** — Send/Submit/Delete/Pay must be a SEPARATE deterministic gate (not the same vision model that read hostile content), showing exact intent/app/target/coords/text. → v2 §4.

## Important
- Screenshot **capture exists** (`lib.rs:2041` screencapture+base64; `ChatInterface.jsx:73` upload) — the gap is loop-grade governed transport+redaction; the command-claim path strips screenshots to metadata (`useDesktopCommandClaims.js:169`). → v2 §1, P5.2 reframed.
- Arbitrary action **names** exist but execute **fixed canary payloads** (`useDesktopCommandClaims.js:49`) — P5.1 adds payload validation + pass-through.
- Session-scoped allowlist is **not** current foundation (global `DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST`; tenant flags unread). → v2 §1.
- Target-window gate is **inert**: `lib.rs:1168` `live_window_matches_target.unwrap_or(true)`. → v2 §1, P5.1 makes it live.
- Claude computer-use is a **new** orchestrator/API integration, not a `ChatCliWorkflow` extension (`workflows.py:1230`). → v2 §2/P5.4.

## Nit
- GLOBAL_MODE is the gesture path; the signed path owns target-binding separately. → v2 §1.
- Session safety must exist **before** the model loop. → v2 §5/§6 re-sequenced (P5.3 < P5.4).
