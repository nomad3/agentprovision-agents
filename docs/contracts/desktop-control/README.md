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

Display-safe invariant (enforced recursively by every parity test): no
`window_title`, `screenshot`, `screenshot_b64`, `clipboard`, `clipboard_text`,
`ocr_text`, `ax_tree`, `page_text`, raw `signature`, or `private_key`. Hashed /
reduced variants (`window_title_hash`, `screenshot_hash`, `title_present`,
`title_chars`, `signature_present`, `envelope_hash`) are allowed.

The `code` values are canonical PR-C `DesktopDenialCode` values from
`apps/api/app/services/desktop_control_codes.py`. API parity tests assert each
deny fixture code is a member of that enum and that `code_for_reason(reason)`
maps back to the same code.

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
