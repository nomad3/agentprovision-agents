# Luna (dashboard, Codex gpt-5.5) platform-fit review — productionization design (v2)

Dispatched via `/dashboard` (TENANT CLI = Codex), session `7aa4462b`, 2026-06-09. Platform-architecture lens (complements the Codex codebase review). **Verdict: sound direction, NOT platform-approved until the Alpha CLI kernel surface + agent-governance boundary are added.**

## Blockers
- **L-B1 — Missing Alpha CLI kernel contract.** Design adds services/routes/client but defines no canonical `alpha <verb>` surface, and doesn't require v1 routes to delegate to the same entrypoints (violates `docs/architecture/alpha_cli_kernel.md`). Required verbs: `alpha desktop capabilities get`, `alpha desktop enablement get|set`, `alpha desktop keys generate|rotate|list`, `alpha desktop allowlist get|set`, `alpha desktop preflight run`, `alpha desktop commands audit|list` (inspection, not actuation issuance). Routes call these service fns, no business logic in `/presence/capabilities` or desktop routes.
- **L-B2 — Agent governance under-specified for the API-native path.** Scoping MCP pointer/keyboard tools out is fine, but the API-native path still needs the platform auth model: a `desktop_observe` / `desktop_control` tool-group split, agent-token scope enforcement, user/JWT permission checks, MCP observe-tool scope alignment. A tenant flag alone is too broad a boundary for native OS actuation.

## Important
- **L-I1 — Event/RL placement.** `publish_session_event` for lifecycle (capability refresh result, approval requested/granted/denied, command enqueued/claimed/denied/completed, Stop/resume, stale-capability disable). `rl_experience` ONLY where Luna/agent autonomy decides (request control, target/app/action choice, retry/escalate) — NOT key rotation, admin toggles, manual preflight.
- **L-I2 — Capabilities must be a thin projection** of `alpha desktop capabilities get`, not a second source of truth. Include policy version, source timestamps, effective flags, key registry, allowlist, expiry, reason codes for disabled states.
- **L-I3 — Admin-only flag mutability.** The `tenant_features` flags fit convention but must be superuser/operator-only, excluded from member-writable tenant updates; allowlist needs operator/admin audit, not member mutation.
- **L-I4 — Single-SSE consumer statement.** Capability refresh can be TTL/poll, but command/session events flow through one shared per-session stream; no per-component desktop streams in Tauri React.
- **L-I5 — Value-arbitration / safety-floor integration.** Approval admission should carry a value/safety verdict or an explicit reason the desktop policy layer is the sole arbitration boundary for this phase. Minimum: safety-floor vetoes, tenant norms, substrate throttling, audit outcome before autonomous actuation.
- **L-I6 — Rollout wording.** "Core feature for all tenants" = "available to every tenant behind default-off enablement," NOT fleet-wide activation. UX gates: tenant-admin enablement, per-device enrollment, TCC readiness, visible mode, Stop, revocation — first-class.

## Nits
- **L-N1** Rename `native_control_enabled` → `pointer_control_enabled` (or document "native" = pointer only).
- **L-N2** Add `desktop_observe_enabled`, or state whether `desktop_control_enabled` gates observation too.
- **L-N3** Platform metrics alongside audit: enabled tenants, active enrolled devices, deny reasons, stale-capability disables, key-rotation success/failure, command deny/complete counts.
- **L-N4** State that future MCP actuation must wrap the same `alpha desktop` verbs + tool-group scopes.
