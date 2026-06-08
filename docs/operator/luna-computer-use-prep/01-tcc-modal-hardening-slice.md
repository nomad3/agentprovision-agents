# Slice 01 — TCC modal hardening (Recheck · Why-needed · stale cleanup · contrast)

**Status:** PROPOSED prep — diffs not applied. macOS-only, read-only, fail-closed, no actuation.
**Scope-in:** Recheck button; per-permission Why-needed copy; stale ad-hoc TCC-entry cleanup
guidance; signed-identity emphasis; contrast/readability/a11y.
**Scope-out:** no `ComputerUsePermissionSheet.jsx` extraction; no schema/migration; no
down-channel; no actuation; no fullscreen change.

**Files touched (4):**
- `apps/luna-client/src/components/ControlSafetyStrip.jsx`
- `apps/luna-client/src-tauri/src/computer_use/permissions.rs`
- `apps/luna-client/src/App.css`
- `apps/luna-client/src/components/__tests__/ControlSafetyStrip.test.jsx`

**Safety invariants that must still hold after this slice:**
`can_control_pointer/keyboard` stay `false`; `tier_enabled` untouched; permission probes stay
passive (no auto-prompt except the explicit Enable/Open click); no raw window title / clipboard /
pixels rendered anywhere; Recheck only calls the read-only `control_get_safety_state`.

---

## A. `ControlSafetyStrip.jsx`

### A1 — Why-needed copy map (module scope, after `PERMISSION_KEYS`, ~line 49)

Plain-language, distinct from the technical `required_for` list. Pure client copy — no schema change.

```jsx
const WHY_NEEDED = {
  screen_recording:
    'So Luna can capture a screenshot to see your screen when you ask it to observe.',
  accessibility:
    'So Luna can read the active app and window. Also required before any future, approval-gated pointer or keyboard help.',
  automation_system_events:
    'So Luna can read the front app and window title via System Events when you ask what you are working on.',
  input_monitoring:
    'Not used in this phase — Luna does not monitor your keystrokes.',
  camera:
    'Only used if you start gesture calibration or camera features. Off by default.',
  microphone:
    'Only used for push-to-talk voice input. Off by default.',
};
```

### A2 — carry `whyNeeded` through `permissionEntries` (~line 131-144)

```diff
       return {
         key,
         label: permissionLabel(key),
         status: value?.status || 'unknown',
         reason: value?.reason || '',
         requiredFor: value?.required_for || [],
+        whyNeeded: WHY_NEEDED[key] || '',
       };
```

### A3 — Recheck state + handler (in component, near other `useState`/`useCallback`)

```diff
   const [permissionBusy, setPermissionBusy] = useState(null);
+  const [recheckBusy, setRecheckBusy] = useState(false);
   const [activeApp, setActiveApp] = useState(null);
```

```jsx
  // Explicit user-driven re-probe. control_get_safety_state recomputes the passive
  // TCC readiness probes on every call, so this reflects fresh System Settings state
  // without arming anything. (App identity is process-static and intentionally cached.)
  const recheck = useCallback(async () => {
    setRecheckBusy(true);
    try {
      await refresh();
    } finally {
      setRecheckBusy(false);
    }
  }, [refresh]);
```

### A4 — Recheck button in modal header (before Close, ~line 463)

```diff
             <div className="control-permissions-header">
               <span className="control-permissions-title">Mac Permissions</span>
               <span className="control-permissions-summary">{permissionSummary.label}</span>
+              <button
+                className="control-permissions-recheck"
+                type="button"
+                disabled={recheckBusy}
+                aria-label="Recheck macOS permission status"
+                title="Re-probe macOS Screen Recording, Accessibility, and other permissions now"
+                onClick={recheck}
+              >
+                {recheckBusy ? 'Rechecking…' : 'Recheck'}
+              </button>
               <button
                 className="control-permissions-close"
```

> Header grid goes from 3 → 4 columns; CSS change in section C.

### A5 — Why-needed line in each permission row (~after the `reason` block, line 507)

Render **before** "Required for:" so the user reads the human reason first, the technical list second.

```diff
                 {permission.reason && (
                   <span className="control-permission-detail">{permission.reason}</span>
                 )}
+                {permission.whyNeeded && (
+                  <span className="control-permission-why">{permission.whyNeeded}</span>
+                )}
                 {permission.requiredFor.length > 0 && (
                   <span className="control-permission-detail control-permission-required">
                     Required for: {permission.requiredFor.join(', ')}
                   </span>
                 )}
```

### A6 — signature-kind emphasis (identity section, ~line 478)

```diff
-                {signatureLabel && (
-                  <span className="control-permissions-identity-line">Signature: {signatureLabel}</span>
-                )}
+                {signatureLabel && (
+                  <span
+                    className={`control-permissions-identity-line ${
+                      identity.code_signature_kind && identity.code_signature_kind.includes('Developer ID')
+                        ? 'control-sig-verified'
+                        : 'control-sig-adhoc'
+                    }`}
+                  >
+                    Signature: {signatureLabel}
+                  </span>
+                )}
```

> The stale-cleanup guidance text itself is **server-authoritative** (lives in the Rust
> `permission_scope_note`, section B) and already renders via the existing
> `control-permissions-identity-note` span — no extra JSX needed for the copy.

---

## B. `permissions.rs` — stale ad-hoc cleanup guidance (scope note, ~line 113-117)

ASCII only (these strings are UI-only, never part of any signed envelope). Append concrete
cleanup steps to both branches.

```diff
     let permission_scope_note = if running_outside_applications {
-        "macOS grants TCC permissions to the running app identity. This Luna is not running from /Applications, so grants for the installed release may not apply to this development build."
+        "macOS grants TCC permissions to the running app identity. This Luna is not running from /Applications, so grants for the installed release may not apply to this development build. If Privacy & Security shows Luna allowed but Luna still reports denied here, remove the stale 'Luna' entries (select each, press the minus button), then grant this build again with the Enable/Open buttons below."
     } else {
-        "macOS grants TCC permissions to the running app identity. If an unsigned or ad-hoc build changes code identity, Privacy & Security may need a fresh Luna entry."
+        "macOS grants TCC permissions to the running app identity. If an unsigned or ad-hoc build changes code identity, Privacy & Security may need a fresh Luna entry. When permissions look granted but Luna still reports denied, macOS is evaluating an older Luna identity: remove the stale 'Luna' entry, then re-grant this build."
     };
```

> No behavioral change — string-only. The non-macOS branch (`current_app_identity_impl`)
> and the `PermissionProbe` reason strings are unchanged.

---

## C. `App.css` — contrast / readability / a11y

### C1 — header 4-column grid (`.control-permissions-header`)

```diff
 .control-permissions-header {
   display: grid;
-  grid-template-columns: 1fr auto auto;
+  grid-template-columns: 1fr auto auto auto;
   align-items: center;
   gap: 10px;
   padding-bottom: 10px;
   border-bottom: 1px solid rgba(130,160,204,0.24);
 }
```

### C2 — Recheck button (new; mirrors Close but reads as the primary re-probe action)

```css
.control-permissions-recheck {
  height: 28px;
  padding: 0 12px;
  border: 1px solid rgba(99,210,151,0.55);
  border-radius: 6px;
  background: rgba(99,210,151,0.16);
  color: #d8ffe8;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.control-permissions-recheck:hover:not(:disabled) { background: rgba(99,210,151,0.24); }
.control-permissions-recheck:disabled { opacity: 0.6; cursor: default; }
```

### C3 — Why-needed line (brighter than the technical detail; clearly the human "why")

```css
.control-permission-why {
  color: #e9eefc;
  font-size: 11.5px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.control-permission-required { color: #8fa3c2; font-size: 11px; }
```

### C4 — status as a tinted pill (scannable at a glance; replaces plain colored text)

```diff
 .control-permission-status {
-  color: #d7e2f5;
+  color: #e7eefb;
   font-weight: 700;
   text-align: right;
   white-space: nowrap;
+  padding: 1px 8px;
+  border-radius: 999px;
+  border: 1px solid rgba(130,160,204,0.34);
+  background: rgba(130,160,204,0.14);
 }
@@
-.control-permission-granted .control-permission-status,
-.control-permission-not_required .control-permission-status { color: #7ce0aa; }
-.control-permission-denied .control-permission-status { color: #ffbfc2; }
-.control-permission-unknown .control-permission-status { color: #c3d1ef; }
+.control-permission-granted .control-permission-status,
+.control-permission-not_required .control-permission-status {
+  color: #b7f3d2; border-color: rgba(99,210,151,0.55); background: rgba(99,210,151,0.16);
+}
+.control-permission-denied .control-permission-status {
+  color: #ffd2d4; border-color: rgba(255,143,143,0.55); background: rgba(255,143,143,0.16);
+}
+.control-permission-unknown .control-permission-status {
+  color: #d6e0f4; border-color: rgba(130,160,204,0.45); background: rgba(130,160,204,0.18);
+}
```

### C5 — signature kind emphasis

```css
.control-sig-verified { color: #b7f3d2; font-weight: 700; }
.control-sig-adhoc { color: #ffdf9b; font-weight: 700; }
```

### C6 — keyboard focus visibility (a11y; none today)

```css
.control-permissions-recheck:focus-visible,
.control-permissions-close:focus-visible,
.control-permission-action:focus-visible,
.control-safety-action:focus-visible,
.control-safety-permissions:focus-visible {
  outline: 2px solid #8fd2ff;
  outline-offset: 2px;
}
```

---

## D. Tests — `ControlSafetyStrip.test.jsx`

The suite already mocks `@tauri-apps/api/core`'s `invoke` and renders the component. Add cases
(reusing the existing readiness fixture; ensure `app_identity.permission_scope_note` contains the
cleanup phrase and at least one `denied` + one `granted` permission):

```jsx
test('Recheck button re-invokes control_get_safety_state', async () => {
  // open the modal, clear prior invoke calls, click Recheck
  // expect invoke to have been called again with 'control_get_safety_state'
});

test('renders a Why-needed explanation distinct from the Required-for list', async () => {
  // expect screen_recording row to show the WHY_NEEDED copy
  // and a separate 'Required for:' line
});

test('renders stale ad-hoc cleanup guidance from the scope note', async () => {
  // fixture scope_note includes "remove the stale 'Luna'"
  // expect that text present in the identity note
});

test('shows signature kind with verified vs ad-hoc emphasis', async () => {
  // ad-hoc fixture -> .control-sig-adhoc ; Developer ID fixture -> .control-sig-verified
});

test('never renders raw window titles or clipboard text (regression)', async () => {
  // assert no fixture raw-title/clipboard string appears in the DOM
});
```

Run: `cd apps/luna-client && npm test -- --run src/components/__tests__/ControlSafetyStrip.test.jsx`
then `npm run build`; `cd src-tauri && cargo test computer_use::` (Rust string change is
covered by existing identity tests; add an assertion that the scope note contains the cleanup
phrase if a permissions unit test exists).

---

## Review checklist before opening PR
- [ ] No actuation paths touched; `can_control_*` still false; `tier_enabled` untouched.
- [ ] Recheck calls only `control_get_safety_state` (read-only).
- [ ] No raw title/clipboard/pixel strings introduced.
- [ ] Rust scope-note strings ASCII-only.
- [ ] Contrast: status pills + why-needed legible on `#162234`/`#1b2432`; focus-visible present.
- [ ] Address every review finding (BLOCKER/IMPORTANT/NIT) in the same PR.
