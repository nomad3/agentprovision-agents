# Desktop-Control Contract Fixtures

Canonical, display-safe golden fixtures for the Luna desktop-control typed
contract. These files are the single shared reference that the API owns and that
every other surface validates against.

## Canonical owner rule (do not violate)

The **API (`apps/api`) is the source of truth** for every desktop-control shape:
the v1 desktop-control routes, `app/services/desktop_control_service.py`
display-safe payloads + `_SAFE_*` allow-lists, `desktop_command` /
`desktop_command_event` models, the `agentprovision.desktop_command_envelope.v1`
envelope, and the PR-C stable denial/error `code` enum.

One owner, three consumers (never the reverse):

1. **API generates / asserts** — the fixtures' enum values are checked against the
   real service constants (`apps/api/tests/api/v1/test_desktop_control_contract.py`).
2. **core (`apps/agentprovision-core`) mirrors** — validates by `include_str!`-ing
   these fixtures (`apps/agentprovision-core/tests/desktop_contract.rs`).
3. **MCP (`apps/mcp-server`) is a passthrough** — returns the API payload unchanged
   and validates it matches the same fixture shape + denial `code`, with raw
   content absent (`apps/mcp-server/tests/test_desktop_control_contract.py`).
   MCP must never reshape or add schema.
4. **CLI (`apps/agentprovision-cli`) consumes core only** — defines no
   desktop-control types of its own
   (`apps/agentprovision-cli/tests/desktop_contract.rs`).

A fixture is authoritative because it tracks the API. If a mirror disagrees with a
fixture, the mirror is wrong.

## Fixtures

| File | Shape | Notes |
|---|---|---|
| `pointer_command_claim.display_safe.json` | native_control pointer command claim | hashed title/screenshot, `signature_present` (no raw signature), agent-requested `action.args` allowed |
| `deny.missing_target_bundle_id.json` | denial — incomplete target binding | `code` = `target_not_allowlisted` |
| `deny.capability_mismatch.json` | denial — capability not matched by grant | `code` = `approval_binding_mismatch` |
| `background_command_claim.display_safe.json` | SP1.5 background-control claim (non-frontmost) | identity beyond PID (bundle + signing/proc/window hashes), `window_bounds` in integer POINTS, hashed message value, independent AX/PID `primitive_flags`, one-window lease |
| `background_control_verified.event.json` | SP1.5 verify-readback success | byte-free proof only: `content_hash_match`, `value_chars`, `structural_state`, `verified` |
| `overlay_event.subscriber_only.json` | SP1.5 overlay/HUD event | `authoritative` = false; `allowed_intents` excludes every authority-granting intent (Stop request only) |
| `background_control_denied.display_safe.json` | SP1.5 background denial | `code` = `pid_reused` (representative); `background_code_for_reason(reason)` maps back to it |
| `observation_status.planner_safe.json` | P5.3b planner-safe observation status (`alpha desktop observe status`) | byte-free + path-free: ids/hash/size/state only; mirrors `DesktopObservationStatusOut` (API) / `PerceptionArtifactStatus` (core) |
| `observation_fetch.denied.json` | P5.3b planner-safe fetch denial | `{detail: {code, reason}}`; `code` is a `PerceptionFetchDenialCode` (`apps/api/app/services/perception_delivery.py`) — a separate closed enum from the frozen PR-C `DesktopDenialCode` |

Display-safe invariant (enforced recursively by every parity test): no
`window_title`, `screenshot`, `screenshot_b64`, `clipboard`, `clipboard_text`,
`ocr_text`, `ax_tree`, `page_text`, raw `signature`, or `private_key`. Hashed /
reduced variants (`window_title_hash`, `screenshot_hash`, `title_present`,
`title_chars`, `signature_present`, `envelope_hash`) are allowed.

The `code` values are canonical PR-C `DesktopDenialCode` values from
`apps/api/app/services/desktop_control_codes.py`. API parity tests assert each
deny fixture code is a member of that enum and that `code_for_reason(reason)`
maps back to the same code.

## SP1.5 — secondary-pointer / background-control contract

The four `background_*` / `overlay_*` fixtures type the **non-frontmost** app-control
path from `docs/plans/2026-06-11-luna-secondary-pointer-background-control.md`
(Luna APPROVE for SP1.5 fixtures only). They are the executable security spec
SP2+ must satisfy; **no native actuation, no AX/CGEvent, no DB.**

- **Codes (§5.3):** the new background denial vocabulary lives in
  `apps/api/app/services/desktop_background_codes.py` as `BackgroundControlDenialCode`
  (a *separate* enum from the frozen PR-C `DesktopDenialCode`). The two reused
  concepts — `stopped` and `secure_input_active` — keep their canonical PR-C
  codes; a background deny `code` must be a member of `ALLOWED_BACKGROUND_DENIAL_CODES`
  (the new tokens ∪ those two). `background_code_for_reason(reason)` maps each
  canonical display-safe reason (and its bare token) to exactly one code.
- **Pure gates:** the same module holds the pure SP1.5 security decisions
  (target identity beyond PID, points-based window/display/title drift, lease
  loss, independent AX-vs-PID primitive flags, verify-readback, overlay
  subscriber-only authority, byte-free event guard). Each is unit-tested in
  `apps/api/tests/api/v1/test_desktop_sp15_contract.py`, covering every §11
  minimum-test line.
- **Byte-free (§10/§13):** background events extend the display-safe boundary
  with WhatsApp/AX-specific raw fields (`message_text`, `contact_name`,
  `chat_title`, `row_text`, `ax_label`, `text`, `value`, …) via
  `FORBIDDEN_EVENT_FIELDS`; the verified-event fixture proves outbound proof is
  hashes/counts/booleans/categories only.
- **Lane-B follow-up (not done here):** the strongly-typed **core** mirror
  (`agentprovision_core::desktop` structs / `DesktopDenialCode`) and the Tauri
  `denial_codes.rs` enum do **not** yet carry the SP1.5 codes/shapes. Extending
  the typed mirror is owned by lane B (PR-D) and is intentionally deferred so
  this SP1.5 fixture PR stays small and does not collide with the frozen typed
  contract. The existing core/MCP/CLI parity suites stay green because they
  validate only the original three fixtures.

## Regeneration (API owner only)

Fixtures track the live service; do not hand-tune semantics. A future dump helper
(`apps/api/.../dump_desktop_contract` — TODO, see the contract test) regenerates
them from real `desktop_control_service` output. Commit regenerated JSON in the
SAME PR as the API change that caused it.

## Parity checks (all must be green)

No cargo workspace exists; run cargo per crate directory.

```
# API — fixture enum values vs real service constants (drift detector):
cd apps/api && pytest tests/api/v1/test_desktop_control_contract.py -q

# API — SP1.5 background-control contract + security gates (pure, no DB):
cd apps/api && pytest tests/api/v1/test_desktop_sp15_contract.py -q

# MCP — passthrough shape + denial code + display-safe:
cd apps/mcp-server && pytest tests/test_desktop_control_contract.py -q

# core — include_str! deserialize + display-safe + enum membership:
cd apps/agentprovision-core && cargo test --test desktop_contract

# CLI — consumes core; defines no desktop types; display-safe:
cd apps/agentprovision-cli && cargo test --test desktop_contract
```

## PR-D gate checklist

- [ ] PR-C denial/error `code` enum merged; fixture `code` values are members of it.
- [ ] Claudia C schema freeze in effect; `key_id` treated as an OPAQUE string.
- [ ] Fixtures track the live API; API contract test green.
- [ ] core mirror + `desktop_contract.rs` green (incl. display-safe negative).
- [ ] MCP passthrough parity green (`"screenshot"`/`"clipboard_text"` absent).
- [ ] CLI consumes core only; CLI test green.
- [ ] API + both mirrors changed in the SAME PR (parity rule).

## Prohibitions

- **No `alpha desktop` command.** Types + parity only; no actuation-adjacent CLI surface.
- **No native actuation.** `desktop_control_allows_actuation()` stays false; these fixtures
  type the shape, they do not authorize execution.
- **No schema drift without an API change + fixture update.** Any shape change MUST: change the
  API, regenerate these fixtures, and update core + MCP mirrors in the SAME PR. No mirror may add
  a field the API does not emit; MCP may not reshape; the CLI may not define its own types.
- **No signing secrets or captured content.** Fixtures are synthetic (zeroed ids, placeholder
  hashes) — never real credentials, keys, screenshots, clipboard, or window titles.
