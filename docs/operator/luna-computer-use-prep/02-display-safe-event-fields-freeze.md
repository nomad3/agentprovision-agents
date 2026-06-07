# Display-safe event field surface — FROZEN v1

The complete set of fields that may cross a display/replay/agent boundary for desktop-control.
Verified read-only against code 2026-06-07. **Invariant:** no raw window title, clipboard text,
screenshot pixels, OCR text, subprocess args, filesystem paths, or tokens appear in any field
below. Adding a field to any allowlist requires council review **and** a schema version bump.

Source of truth: `apps/api/app/services/desktop_control_service.py`,
`apps/api/app/api/v1/activities.py`, `apps/luna-client/src/utils/macosAppMonitor.js`,
`apps/luna-client/src-tauri/src/lib.rs`.

---

## 1. `session_events` display mirror
`_publish_display_safe_command_event` → `_publish_display_safe_session_event`
(`desktop_control_service.py` ~1502-1523). Mirrored payload keys — **FROZEN**:

```
desktop_event_id, desktop_command_id, shell_id, device_id,
approval_id, capability, status, outcome, reason
```
`reason` passes redaction of client-supplied text before mirror. Nothing else is mirrored.

## 2. `desktop_command_events.metadata` allowlist
`_SAFE_METADATA_KEYS` (`desktop_control_service.py:101-118`) — **16 keys, FROZEN**
(note: an earlier audit said "20"; the live set is 16):

```
can_observe, control_mode,
envelope_config_error, envelope_hash, envelope_nonce,
envelope_policy_version, envelope_signing_algorithm,
approval_id, approval_remaining_actions, approval_risk_tier,
payload_key_count, result_fields, result_kind,
result_size_bytes, result_size_chars, tool_name
```
Enforced by `_safe_metadata()` (~328-380); unknown keys are dropped.

## 3. Observation result fields (the only content returned toward the agent)
- `_SAFE_RESULT_FIELDS` (`:121`) — **FROZEN:** `{ app, title_chars, title_present }`
- `_SAFE_RESULT_KINDS` (`:120`): `{ binary, string, json, error, unsupported, unknown }`
- `_SAFE_CONTROL_MODES` (`:122`): `{ control_locked, observe, stopped }`

Client mirror — `safeObservationMetadata()` (`useDesktopCommandClaims.js:127-147`):
`read_clipboard → {result_kind, result_size_chars}`;
`capture_screenshot → {result_kind, result_size_bytes}`;
`get_active_app → {result_kind, result_fields ⊂ {app,title_present,title_chars}}`.

## 4. `user_activities` (ambient app-switch audit)
`activities.py:64-99,169` — **FROZEN:** `window_title` forced to `None`; for `app_switch`
only `window_title_present` (bool) + `window_title_chars` (int) stored; `subprocess`/`app_name`
excluded via `model_dump(exclude=...)`.

## 5. `macos_app_monitor_event.v1` (Tauri → React → API)
Emitter `build_macos_app_monitor_event` (`lib.rs:1878-1892`); sanitizer
`sanitizeMacosAppMonitorEvent` (`macosAppMonitor.js:50-80`). **FROZEN:**

```
schema = "agentprovision.macos_app_monitor_event.v1"
event_id (uuid), type = "app_switch", platform = "macos",
detail_level = "metadata_only",
from_app, to_app, duration_secs, timestamp,
window_title_present (bool), window_title_chars (int)
```
No raw title / subprocess / cwd / project label passthrough.

## 6. `get_active_app` direct result
`build_active_app_metadata` (`lib.rs:1895-1901`) — **FROZEN:** `{ app, title_present(bool),
title_chars(int) }`. Command Palette consumes only `app` (`CommandPalette.jsx:38-39`).

---

## Known out-of-surface raw-content path (flagged, not part of this freeze)
The ambient `clipboard-changed` Tauri event → `ClipboardToast` → `/api/v1/knowledge/entities`
(`lib.rs` ~2274) carries **raw clipboard text** on a path **outside** desktop-control audit.
It does not violate the channels frozen above, but it is a real raw-content surface. Tracked as
P2 in the readiness report: route it through governed display-safe audit or disable it. Owner: TBD.

## For Claudia B
The union of sections 1–6 is the display-safe contract Alpha CLI/core must type against for
observation results, audit replay, permission/monitor state. Treat result/metadata/mirror field
lists as closed enums; surface the denial taxonomy (see `03`) rather than raw reasons.
