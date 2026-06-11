# Luna Phase 5.4a — Secondary Pointer / Background App Control

**Status:** v2 — Luna Supervisor review folded · **Date:** 2026-06-11 · **Owner:** nomade

## 1. Problem

The current pointer path is still built around the macOS system cursor. The
Phase 3/5 canary uses `enigo` from `gesture/cursor.rs`, which means Luna drives
the same cursor the operator is using. That creates two coupled failures:

- The operator cannot keep working while Luna acts, because Luna and the human
  share one pointer.
- Global coordinate math becomes a product risk. The WhatsApp send-click smoke
  exposed the concrete bug: normalized coordinates were mapped through the main
  display's pixels, then posted through a point-based cursor API. On Retina /
  multi-display setups this can overshoot and miss the intended target.

macOS has one hardware cursor. Luna cannot create a true second hardware pointer
without a virtual-HID driver, and that is not the right first production path.
The product requirement is the user-visible behavior of a second pointer: Luna
can operate a target app while the operator's mouse and keyboard remain usable.

## 2. Decision

Build Luna's "secondary pointer" as **scoped target-app injection plus an overlay
pointer/HUD**, not as global cursor warping.

Primary mechanism:

- **AX-first app control.** Use Accessibility to find target UI elements and
  invoke/set them directly: message field, buttons, menu items, focused controls,
  and window-local element frames. No global cursor movement.

Fallback mechanism:

- **PID/window-scoped event posting.** Use `CGEventPostToPid` only when AX cannot
  express the action, and only with a live target PID + verified target window
  bounds. The event is posted to the target app process, not by moving the
  operator's cursor. This is degraded/high-risk fallback behavior: it requires a
  distinct capability flag and explicit signed allowance for the specific
  primitive action. It must never be reached merely because an AX attempt failed.

Visibility mechanism:

- **Overlay pointer + HUD.** Render Luna's intended action point as an app-owned
  overlay sprite/HUD with target app, action, capability, and Stop state. This is
  cosmetic and auditable; it is not the input mechanism.

The existing `enigo` global-cursor path remains as the fixed canary and as a
regression target, but it must not be the primitive for general app control.

## 3. Security Boundary Change

Full background parallelism means Luna can act in an app that is not frontmost.
That intentionally retires the old frontmost-app requirement for this path, but
only after replacing it with stricter target binding.

Old gate:

```
operator-approved command
  -> signed envelope
  -> Luna verifies
  -> target app must be frontmost
  -> global cursor/keyboard event
```

New gate:

```
operator-approved command
  -> signed envelope
  -> Luna verifies tenant/user/session/device/key/nonce/command
  -> short-lived target-window lease is active
  -> target bundle + target process/window identity are live and not reused
  -> target app is allowlisted and enabled for this tenant/capability
  -> target PID/signing identity/window bounds match the signed target within tolerance
  -> secure-input and Stop/Lock are rechecked immediately before each action
  -> scoped AX action or explicitly allowed PID/window-scoped event
  -> local-only verify-readback confirms the intended state changed
  -> byte-free audit/result event
```

The target app no longer has to be frontmost, but a command cannot fall back to
"whatever is frontmost" or "wherever the cursor currently is."

## 4. Invariants

1. The operator's system cursor is never moved by the background-control path.
2. The operator's keyboard focus is never stolen as a normal success condition.
3. AX element actions are preferred over coordinates.
4. Coordinate fallback is window/PID-scoped, not display/global-cursor-scoped.
5. Every action must bind to the signed target bundle, signing/team identity
   where available, PID, window identity, bounds, capability, tenant, user,
   session, device, key id, nonce, and command id.
6. PID alone is never identity. PID reuse, app relaunch, app quit, target
   observation expiry, or missing signing identity proof denies.
7. Every action needs a short-lived target-window lease for one target window
   and capability. Lease loss, Stop, Lock, target drift, tenant flag revocation,
   or app quit cancels every pending action.
8. Every action must re-check Stop/Lock and secure input immediately before the
   native call.
9. Background actuation must verify-readback. AX no-op, missing element, stale
   window, wrong app, wrong text/value, or changed bounds fail closed.
10. Readback may compare sensitive values locally inside the client, but logs,
    SSE, audit rows, and chat messages may emit only hashes, lengths,
    categories, booleans, structural proofs, and denial codes.
11. Overlay/HUD state is display-only and must never authorize an action.
12. Overlay/HUD Stop may flow to the local kill path. Overlay/HUD resume,
    approve, replay, mutate-envelope, or extend-lease authority is forbidden.
13. Logs, SSE, audits, and Luna chat state remain byte-free and secret-free.
14. Global `enigo` actuation remains canary-only and must not be used for general
    app-control commands.

## 5. API / Contract Shape

The command envelope needs a target block strong enough for a non-frontmost app:

```json
{
  "target": {
    "bundle_id": "net.whatsapp.WhatsApp",
    "signing_team_id_hash": "<sha256 or null>",
    "audit_token_hash": "<sha256 or null>",
    "window_id": "<client-observed opaque id>",
    "pid": 12345,
    "window_title_hash": "<sha256 or null>",
    "window_bounds": {"x": 0, "y": 0, "width": 900, "height": 700},
    "display_id": 1,
    "observed_at": "2026-06-11T00:00:00Z",
    "expires_at": "2026-06-11T00:00:10Z",
    "lease_id": "<signed short-lived lease id>",
    "command_id": "<desktop command id>",
    "target_role": "message_input|send_button|generic_point",
    "target_element_hint": {
      "ax_role": "AXButton",
      "label_hash": "<sha256 or null>"
    }
  }
}
```

Rules:

- The server signs only canonical, bounded target metadata.
- The client verifies the signed target and re-resolves the live app/window.
- The target observation expires quickly. A stale observation or replayed nonce
  is denied before target resolution.
- PID reuse is denied by binding PID to additional process identity: bundle id,
  signing/team identity where available, audit-token-derived identity where
  available, launch-time/proc metadata where available, and the signed window id.
- Raw titles, screenshots, clipboard contents, and element labels do not cross
  the boundary. Hashes/counts/categories only.
- The API may issue app-specific actions like `whatsapp_send_message`, but the
  signed native envelope still resolves to bounded primitive actions:
  `ax_set_value`, `ax_press`, `pid_post_key`, `pid_post_click`.
- Primitive actions are independently gated. `ax_set_value`, `ax_press`,
  `pid_post_key`, and `pid_post_click` must each have explicit capability policy
  and signed allowance; PID fallback does not inherit AX approval.

## 5.1 Lease / Ownership Contract

Background actuation uses a short-lived lease over exactly one target app/window
and one capability. The lease is signed into the envelope and rechecked on both
server and client sides.

Lease denies:

- lease missing, expired, replayed, or already consumed
- command id mismatch
- target app quit or relaunched
- PID reuse suspected
- signed window id missing or no longer owned by the signed app
- tenant flag, per-capability flag, AX action flag, or PID fallback flag revoked
- Stop or Lock latched
- target app/window drift beyond tolerance

The server enforces lease/capability state at enqueue and claim. The client
enforces the same state immediately before each native action and before
readback.

## 5.2 Window Drift / Coordinate Contract

All bounds comparisons are in **points**, not pixels. Display and Retina scale
are explicit metadata, not inferred from global cursor APIs.

Rules:

- Bounds tolerance is a small points-based threshold defined in fixtures before
  implementation.
- Display id change denies unless the target is re-observed and re-signed.
- Window minimized, hidden, off-screen, no longer owned by the signed app, or
  unreadable for verification denies.
- Occlusion that prevents readback denies; Luna must not click blindly through
  uncertain window state.
- PID fallback coordinates are window-relative points and are posted only to the
  signed target PID/window after the drift check passes.

## 5.3 Denial-Code Contract

SP1.5 must add stable byte-free reason codes before native work starts:

- `wrong_bundle`
- `stale_pid`
- `pid_reused`
- `missing_window`
- `bounds_drift`
- `display_drift`
- `title_hash_drift`
- `signing_identity_mismatch`
- `secure_input`
- `stopped`
- `locked`
- `lease_lost`
- `flag_disabled`
- `fallback_not_allowed`
- `readback_failed`
- `raw_bytes_blocked`
- `overlay_not_authoritative`

Events may include codes, booleans, counts, hashes, lease ids, command ids, and
coarse target categories. Events must not include raw titles, contact names,
message text, visible row text, AX labels, screenshots, or clipboard contents.

## 6. Client Architecture

New native modules under `apps/luna-client/src-tauri/src/computer_use/`:

- `target_app.rs`: resolve bundle -> running app PID(s), target window metadata,
  target-alive decision, process signing identity, PID reuse suspicion, bounds
  drift, title-hash drift.
- `ax_target.rs`: find AX elements by role/hint, perform `AXPress` /
  `AXSetValue`, and read back element value/state.
- `scoped_event.rs`: `CGEventPostToPid` fallback with window-relative coords.
- `secondary_pointer.rs`: orchestrates AX-first, scoped-event fallback, final
  Stop/secure-input checks, verify-readback, and result reason codes.
- `overlay_hud.rs` or React/Tauri bridge: emits Luna pointer/HUD preview events
  without granting authority.

Existing `gesture/cursor.rs` stays isolated for:

- gesture UI canary
- fixed pointer canary
- regression tests that prove general app control does not call global cursor
  movement

## 7. Server / Alpha Kernel

All surfaces continue to go through the Alpha CLI kernel and thin v1 routes:

- `alpha desktop observe request`
- `alpha desktop commands audit|list`
- `alpha desktop command request` (new, or equivalent governed verb)
- `alpha desktop preflight run`
- `alpha desktop allowlist get|set`

Server-side requirements:

- tenant flag + per-capability flag checked at enqueue and claim
- independent action/fallback flags for `ax_set_value`, `ax_press`,
  `pid_post_key`, and `pid_post_click`
- target allowlist effective = tenant allowlist intersect platform floor
- command envelope includes target binding for background control
- server issues and verifies a short-lived target-window lease
- event stream includes `background_control_started`, `background_control_denied`,
  `background_control_verified`, and `background_control_failed`
- no direct MCP actuation route bypasses Alpha/tool-group governance

## 8. Verification Model

Each action class needs a readback rule:

| Action | Success proof | Fail-closed examples |
|---|---|---|
| `ax_set_value` | AX value equals requested text or accepted normalized value | value unchanged, field disappeared, secure input active |
| `ax_press` | target app emits expected state change or AX tree state changes | press no-op, wrong element, stale window |
| `pid_post_key` | focused target element value/selection changes as expected | focus stolen, no readback, target not alive |
| `pid_post_click` | hit-test target remains within signed bounds and state changes | bounds drift, target moved, no readback |

For WhatsApp send:

1. AX-find message input in `net.whatsapp.WhatsApp`.
2. AX-set message text.
3. Verify input value contains the intended text.
4. AX-find send button or use Enter only if the signed action explicitly allows
   submit.
5. Press.
6. Verify input cleared or sent-message row appears with a bounded, non-secret
   structural proof. Do not log message content.

Readback privacy rules:

- Plain text comparisons happen only inside the Luna client process.
- Outbound proof is limited to content hash match, length match, structural
  state, and denial code.
- WhatsApp-specific proof must not emit message text, contact names, chat titles,
  visible row text, or raw AX labels.
- PID-posted key events must prove they affected the signed target element, not
  the operator's active focus. If proof is unavailable, deny.

## 9. Overlay / HUD UX

The overlay is a visible control surface, not an input primitive.

Required states:

- target app/bundle
- action type
- "observing", "acting", "verified", "denied", "stopped"
- Stop button always visible when Luna is acting
- degraded indicator when AX fallback to PID-scoped events is used

The overlay pointer should be rendered in target-window coordinates and should
not imply global cursor ownership. It should disappear immediately on Stop,
target drift, failed readback, or lease loss.

Overlay authority rules:

- The overlay subscribes to command/lease/HUD events only.
- It may request Stop through the local kill path.
- It must not generate, mutate, approve, extend, or replay command envelopes.
- It must not resume or unlock background actuation.

## 10. PR Ladder

1. **SP1 design + contract fixtures**
   - Add this design.
   - Add contract fixtures for background target binding and denial reason codes.
   - No native actuation code.

2. **SP1.5 contract/security fixtures**
   - Add fixtures for target identity, lease loss, replay, PID reuse,
     coordinate-space normalization, byte-free event shape, and denial codes.
   - Prove raw titles, labels, message text, screenshots, and clipboard content
     cannot appear in events.
   - No native actuation code.

3. **SP2 target-app resolver**
   - Client can resolve running bundle/PID/window metadata.
   - Pure tests for target-alive, signing identity, PID reuse, bounds drift,
     display drift, coordinate-space normalization, and title-hash drift.
   - No AX actions, no events posted.

4. **SP3 AX probe + dry-run**
   - Read-only AX tree probe for allowlisted target app.
   - Emits display-safe element metadata only.
   - Proves WhatsApp exposes message field/send control without pressing them.

5. **SP4 overlay pointer/HUD**
   - React/Tauri event bridge and HUD rendering.
   - Subscriber only; Stop request allowed, no resume/approve/replay authority.

6. **SP5 AX action path behind default-off flag**
   - `ax_set_value` / `ax_press` with verify-readback.
   - Operator-only, WhatsApp-only, default off, Stop preemption test.

7. **SP6 PID/window-scoped fallback**
   - `CGEventPostToPid` fallback for unsupported AX controls.
   - Requires target alive + window bounds + readback.
   - Separate review gate before SP7; AX success does not authorize PID fallback.

8. **SP7 retire frontmost gate for signed background actuator**
   - Only after SP2-SP6 tests pass.
   - Retire frontmost only for this signed background actuator.
   - Frontmost remains required for the old global-cursor canary and gesture
     global-cursor path.

9. **SP8 E2E runbook and release gate**
   - Installed Luna app smoke on multi-display Retina setup.
   - Operator keeps using cursor while Luna sends a WhatsApp self-chat message.
   - Verify Stop, target drift, app quit, secure input, flag-off, revoked tenant
     flag, and wrong-bundle denies.

## 11. Tests

Minimum tests before any live background actuation:

- target binding rejects missing PID/window id/bounds
- wrong bundle denies
- stale PID denies
- PID reuse denies
- signing identity mismatch denies
- window bounds drift denies
- display drift denies
- title hash drift denies when title binding is present
- secure input denies keyboard-like actions
- Stop denies before every native call
- lease loss denies every pending action
- AX no-op denies if readback fails
- overlay events cannot authorize action
- overlay can Stop but cannot resume, approve, mutate, replay, or extend leases
- global cursor functions are not called by background-control commands
- tenant flag revoke between enqueue and claim denies
- wrong key/nonce/replay still denies before target resolution
- AX approval does not permit PID fallback
- PID-posted events deny when target-element readback is unavailable

## 12. Open Risks

- Some apps expose incomplete AX trees. That is why PID-scoped fallback exists,
  but fallback must be treated as lower confidence and require stronger readback.
- Background synthetic events are app-dependent. They may no-op silently; readback
  is mandatory.
- Secure Input is process-global, not per-field. When active, fail closed for
  keyboard/text actions even if the target app is not frontmost, unless a future
  reviewed exception has proof that it cannot leak or affect secure entry.
- AX readback can reveal user text. Readback used for verification must be local
  and must not be logged or sent to the API except as byte-free success/failure.
- The overlay could mislead the operator if it lags. Overlay state must be tied
  to command lease/session ids and expire aggressively.

## 13. Luna Supervisor Review Result

Luna reviewed the first draft on 2026-06-11 and returned **CHANGES** rather than
approval. The required changes folded into this v2 are:

- hard target identity model beyond PID
- target-window lease/ownership semantics
- points-based drift and multi-display/Retina coordinate rules
- independent AX and PID fallback flags
- local-only readback privacy
- overlay subscriber-only authority
- secure-input and focus proof semantics
- byte-free denial-code/event contract
- SP1.5 before resolver implementation and a separate PID-fallback review gate

Luna reviewed v2 on 2026-06-11 and returned **APPROVE** for SP1 design and
SP1.5 contract/security fixtures only. The approval does not extend to SP2 or
any native resolver/action implementation.

Supervisor call remains: **do not start SP2 until SP1.5 contract/security
fixtures are added and reviewed.**

## 14. Immediate Next Step

Land SP1 as a design-only PR, then implement SP1.5 contract/security fixtures
and ask Codex + Luna for blocker-focused review before SP2. Do not implement AX
actions, `CGEventPostToPid`, or frontmost gate retirement until SP1.5 is reviewed
and the contract fixtures are agreed.
