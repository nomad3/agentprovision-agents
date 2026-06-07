# Luna macOS Computer-Use — UX/Schema Prep Package (Claudia C)

Surgical-prep artifacts for the macOS computer-use UX/schema lane. **Prep only** — the
feature-source edits below are *proposed* (drop-in diffs), not applied. No native
actuation. No branches/commits/pushes/PR/releases until Codex opens a slice.

Ground truth: [`docs/plans/2026-06-05-luna-tauri-computer-use-control-plan.md`](../../plans/2026-06-05-luna-tauri-computer-use-control-plan.md)
· branch `codex/luna-envelope-key-registry` · verified read-only against code 2026-06-07.

## Contents

| File | Purpose | Consumer |
|---|---|---|
| [`01-tcc-modal-hardening-slice.md`](01-tcc-modal-hardening-slice.md) | First safe PR slice: Recheck, Why-needed, stale ad-hoc cleanup guidance, contrast/readability. Exact JSX/Rust/CSS diffs + tests. | Codex (apply when slice opens) |
| [`02-display-safe-event-fields-freeze.md`](02-display-safe-event-fields-freeze.md) | Frozen v1 display-safe field surface (session_events mirror, command-event metadata allowlist, result fields, activity fields). | Codex + Claudia B |
| [`03-schema-freeze-handoff-B.md`](03-schema-freeze-handoff-B.md) | Typed-model contract for Alpha CLI/core parity, with API+Tauri source anchors, enums, FROZEN vs PROVISIONAL markers, route + denial-taxonomy lists. | Claudia B |

## Lane boundaries (unchanged)

- macOS only. Native pointer/keyboard actuation stays hard-disabled (15 verified gates).
  Do not touch `desktop_control_allows_actuation`, `tier_enabled`, or the `*_DISABLED_NATIVE_CONTROL_*` paths.
- Read-only/surgical prep. No git or release actions. Codex owns merge/release;
  Claudia A watches PR #818/#820 gates; Claudia B owns Alpha CLI/core typed models.
- `docs/operator/work-automation.md` is Codex's — not touched.

## Status of the targeted gaps (verified)

- **Recheck button** — absent (`refresh()` is mount/focus/visibility-only). Slice 01 adds it.
- **Why-needed copy** — absent (only technical "Required for"). Slice 01 adds it.
- **Stale ad-hoc cleanup guidance** — absent (scope note explains binding but no cleanup steps). Slice 01 adds it.
- **Signed-app identity** — already rendered (`Signature: <kind> | <id> | team <team>`); shows `Developer ID` on signed builds. Slice 01 only adds kind-based emphasis.
- **Contrast/readability** — focus-visible outlines absent; status is plain colored text; why-vs-required not visually separated. Slice 01 addresses.
- **Display-safe fields** — verified no raw leak; frozen in 02 (note: the live metadata allowlist is **16 keys**, not 20).
- **fullscreen-default** — out of scope this turn. Implemented + validated state is `fullscreen:false` + `maximized:true` (`tauri.conf.json:17,23,41`), window measured at the visible frame; treat maximized-default as intended unless the operator says otherwise.

## How to apply (when Codex opens the slice)

1. Apply diffs in `01` to `apps/luna-client/src/components/ControlSafetyStrip.jsx`,
   `apps/luna-client/src-tauri/src/computer_use/permissions.rs`, `apps/luna-client/src/App.css`,
   and `apps/luna-client/src/components/__tests__/ControlSafetyStrip.test.jsx`.
2. `cd apps/luna-client && npm test -- --run src/components/__tests__/ControlSafetyStrip.test.jsx`
   and `cd src-tauri && cargo test computer_use::`.
3. `npm run build`. Push via CI per the no-local-build rule. PR assigned to nomade.
