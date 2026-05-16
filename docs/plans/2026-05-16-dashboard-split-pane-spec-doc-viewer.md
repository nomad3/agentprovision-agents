# Implementation Plan: VSCode-Style Right-Pane Splits for the Alpha Control Center

**Author:** dashboard squad (planning subagent)
**Date:** 2026-05-16
**Status:** Plan only — depends on landing of `<ResizableSplit>` and `FileTreePanel`/`FileViewer`.

---

## 1. Background and goals

The Alpha Control Center (`/dashboard`, `apps/web/src/pages/DashboardControlCenter.js`) currently renders a 3-pane horizontal split via the new `<ResizableSplit>`:

1. Sessions list (left)
2. Chat thread(s) — already supports an inner nested `<ResizableSplit>` of multiple "editor groups" (chats side-by-side)
3. `<AgentActivityPanel>` (right; Pro mode only)

A separate parallel track lands a `<FileTreePanel>` + `<FileViewer>` that knows how to list/read tenant and platform files (`docs/plans/`, `memory/`, workspace).

**This plan composes those two streams** so a user can open any file from the tree as a pane in the right column, next to (or instead of) `AgentActivityPanel`, mirroring VSCode's "Open to Side" affordance. The right column becomes a generic **pane stack** of heterogeneous items — chat, doc, or activity — wrapped in a single uniform pane chrome.

### Non-goals (out of scope for v1)
- Tab bars per pane (drag-tab-between-panes; deferred to v2 — see Section 9)
- Vertical splits (rows); v1 is columns only
- Dragging tree rows with HTML5 drag-and-drop into the right column
- Multi-window pop-out
- Editing files in the viewer (FileViewer stays read-only)
- Persisting which session is in a `chat` pane in the right column when the session is later deleted (we render an "unavailable" placeholder)

---

## 2. UI flow for "Open to Side"

### Decision: `[⇆ open right]` icon on each file-tree row

Three candidates were considered:

| Option | Pros | Cons |
| --- | --- | --- |
| Right-click → "Open to Side" | VSCode-canonical, no row clutter | Adds a brand-new context-menu primitive (not used elsewhere in the app); discoverability is poor on first launch; mobile/tablet hostile |
| `[⇆]` icon on each row | Discoverable, one click, fits existing button-icon pattern in `FileTreePanel`/`dcc-session-row` | Slight row-width pressure; small visual noise |
| Shift+click | Zero UI weight | Invisible to new users; collides with browser/OS conventions in some shells |

**Choice: icon button**, justified because:
- The rest of the app uses inline action buttons (`+`, `⚡ A2A`) — no existing context-menu pattern means the right-click route is the biggest UX/code lift.
- It's the only option that is immediately discoverable for the new "spec-doc viewer" concept the product team is trying to teach.
- It composes well with v2 tabs (the same button becomes "Open to Side" while a primary single click opens "in current pane").

Concretely, in `FileTreePanel.js` each `file`-kind `TreeNode` row renders the existing `<span class="ftp-name">` plus a secondary `<button class="ftp-open-side">` that is shown on row hover/focus. Clicking it calls a new prop callback `onOpenToSide({ path, scope })`. The default `onClick` behaviour (which currently calls `onSelect`) stays — for users on a layout that doesn't have the right column visible (e.g. simple mode collapsed), the legacy "open in viewer pane" still works.

For keyboard accessibility, the row also reacts to `Shift+Enter` while focused — this is cheap to add and gives power-users parity without surfacing it in UI.

---

## 3. Pane model

The right column owns an ordered list of **pane items**, each a tagged union:

```
PaneItem =
  | { id: string, kind: "chat",     sessionId: string | null }
  | { id: string, kind: "doc",      scope: "tenant"|"platform", path: string }
  | { id: string, kind: "activity" }
```

- `id` is a stable client-side UUID (`crypto.randomUUID()`), used as React key and for focus/close ops, independent of `sessionId`/`path`.
- Default state on first paint: `[{ id: "act-0", kind: "activity" }]`. This preserves today's UI exactly.
- Opening a doc to the side **appends** a `{kind: "doc"}` item if no item for the same `{scope,path}` exists; otherwise it **focuses** the existing pane.
- A future "Split chat to right column" affordance would `push({kind:"chat", sessionId})`.

### Invariants
- The right column may be empty (Simple mode). When empty, `<ResizableSplit>` falls back to the existing two-pane layout (sessions + chat).
- Maximum panes in the right column: **3** (constant `MAX_RIGHT_PANES = 3`).
- Closing the last `activity` pane does *not* remove it permanently; an "Activity" tab strip (Section 4) lets the user re-open it.

---

## 4. Sticky agent activity

`<AgentActivityPanel>` must remain reachable even when the user has filled the right column with documents.

**Choice: thin tab strip at the top of the right column** when other panes are present, click expands it into a real pane. A 28px-tall row showing `● Live activity` (red dot when there's recent SSE traffic — wire to `useSessionEvents` from `SessionEventsContext`). Clicking it appends the `activity` pane back into the pane array.

Behaviour rules:
1. If `panes.length === 1 && panes[0].kind === 'activity'` → render activity pane as today (no chip).
2. If `panes.length >= 1 && some(kind === 'activity')` → render normally; no chip.
3. If `panes.length >= 1 && none(kind === 'activity')` → render chip + the doc/chat panes. Click chip → restore activity.
4. In Simple mode, the right column is hidden entirely.

---

## 5. Pane component contract

A new component `<PaneItem>` (file: `apps/web/src/dashboard/panes/PaneItem.js`) wraps **every** right-column pane and provides uniform chrome:

```
<PaneItem
  item={PaneItem}      // { id, kind, ... }
  focused={boolean}    // true → blue focus border
  title={string}       // computed by parent
  onClose={() => void} // hide for `activity` (close button absent)
  onFocus={() => void} // called on mousedown anywhere in the card
>
  {children}
</PaneItem>
```

It renders:
- An `ap-card` shell consistent with the rest of the dashboard
- Header: title (truncated, `title=` tooltip with full path), kind-badge (`md`, `chat`, `activity`), close button (✕)
- Focus ring (`:focus-within` + explicit `.focused` class)

Body picked by parent:
- `chat` → `<ChatTab sessionId={item.sessionId} session={...}/>`
- `doc` → `<FileViewer file={{path, scope}} embedded />`
- `activity` → `<AgentActivityPanel collapsed={false} sessionId={activeSession?.id ?? null}/>`

`<PaneItem>` deliberately does **not** know about pane *kinds*.

---

## 6. State persistence

- Key: `apControl.rightPane.items`
- Value: JSON-stringified array of `PaneItem`. We persist `kind`, `sessionId`, `scope`, `path` and recreate `id` on hydrate.
- Hydration rules:
  - `chat` items whose `sessionId` is not in the current sessions list → render a "Session unavailable" placeholder PaneItem with a single "Remove pane" CTA.
  - `doc` items whose file no longer exists → `<FileViewer>` already surfaces a 404; sufficient.
  - If hydration throws → fall back to `[{kind:'activity'}]` and `console.warn`.
- Also persist focused pane id under `apControl.rightPane.focusedId`.

---

## 7. Right column rendering — integration with `<ResizableSplit>`

The existing `<ResizableSplit>` (Pane 3) becomes a **nested** `<ResizableSplit>` containing 1..N `<PaneItem>` children when `panes.length > 1`. When `panes.length === 1`, render the single PaneItem flat.

### Sizing
- Outer split: existing logic. Storage key: `dcc.chatRow.sizes.<mode>` (unchanged).
- Inner right-column split: storage key `dcc.rightPane.sizes` (mode-agnostic).
- Default sizes: equal partition (`100/n` each). Min sizes: `200px` per pane.
- Re-key the inner `<ResizableSplit>` with `key={panes.map(p=>p.id).join('|')}` so it re-derives default sizes on add/remove.

### Focus model
- Mousedown anywhere in a pane → `setFocusedPaneId(item.id)`.
- Clicking a sessions-list row while a chat pane is focused **in the right column** routes the new session id to that pane.
- Dashboard tracks `focusedGroupId` (centre) and `focusedRightPaneId` (new). A single `lastFocusedColumn: 'centre'|'right'` state picks which gets the session click.

---

## 8. `FileViewer` `embedded` prop

When mounted *inside* a `<PaneItem>`, the chrome would duplicate. The `embedded` prop signals "render only the body":

- `embedded === false` (default): unchanged.
- `embedded === true`: skip the `<header class="fv-header">`. PaneItem chrome shows scope + path. Truncated flag becomes a small badge near PaneItem title via a `headerAccessory` slot or `onMeta` callback.

---

## 9. Tabs vs splits — v1 vs v2

**v1 is splits only.** Each `<PaneItem>` shows exactly one item.

**v2 (separate plan, not now)** would promote `PaneItem` to `PaneGroup` containing `tabs: PaneItem[]` + `activeTabId` with HTML5 drag-and-drop reordering.

---

## 10. Concrete file-edit list

### New files

1. **`apps/web/src/dashboard/panes/PaneItem.js`** — uniform chrome wrapper. ~80 LOC.
2. **`apps/web/src/dashboard/panes/PaneItem.css`** — `.pane-item`, `.pane-item-header`, `.pane-item-body`, `.pane-item.focused`. ~60 LOC.
3. **`apps/web/src/dashboard/panes/useRightPanes.js`** — custom hook owning `panes`, `focusedPaneId`, persistence, ops `openDocToSide`, `closePane`, `focusPane`, `restoreActivity`. ~120 LOC.
4. **`apps/web/src/dashboard/panes/ActivityChip.js` (+ `.css`)** — thin "Live activity" strip. ~40 LOC.

### Modified files

5. **`apps/web/src/pages/DashboardControlCenter.js`**
   - Import `useRightPanes`, `PaneItem`, `ActivityChip`.
   - Replace Pane-3 block with conditional render based on `panes.length`.
   - Extend outer `<ResizableSplit>` key: `key={'chat-row-' + mode + '-' + rightVisible}`.
   - Wire `selectSessionForFocusedGroup` to handle right-column chat panes.
   - Add `RightPaneContext` provider carrying `{ openDocToSide(file) }`.

6. **`apps/web/src/dashboard/FileTreePanel.js`**
   - Add hover-visible `<button class="ftp-open-side" title="Open to Side">⇆</button>`.
   - Read `openDocToSide` from `RightPaneContext` (graceful no-op fallback).
   - Click: `e.stopPropagation(); openDocToSide({ path: fullPath, scope })`.
   - Shift+Enter shortcut on file rows.

7. **`apps/web/src/dashboard/FileTreePanel.css`** — row hover state shows `.ftp-open-side`; `opacity: 0` otherwise.

8. **`apps/web/src/dashboard/FileViewer.js`** — add `embedded` prop. When true, skip `<header class="fv-header">`. Add `onMeta?.({ truncated })` callback for PaneItem to render the badge.

9. **`apps/web/src/pages/DashboardControlCenter.css`** — right-column stack height rules matching existing `.dcc-chat-row` clamp.

### Untouched but verified
- `AgentActivityPanel.js` — props (`collapsed`, `sessionId`) already match.
- `tabs/ChatTab.js` — self-contained; renders fine inside `<PaneItem>`.
- `SessionEventsContext.js` — single SSE per `activeSession` is correct.

---

## 11. Test plan

### Manual smoke
1. **Default render — back-compat.** `/dashboard` Pro mode. Right column shows `AgentActivityPanel` exactly as before.
2. **Default render — Simple mode.** Right column hidden. No activity chip.
3. **Open a plan doc.** Expand `docs/plans/`, hover `.md` row, click `⇆`. Right column → 2 panes (activity + doc); markdown rendered.
4. **Scroll markdown.** Doc pane scrolls independently. Activity pane keeps streaming SSE without scroll reset.
5. **Close doc.** ✕ on doc PaneItem. Right column reverts to single `AgentActivityPanel`.
6. **Hide then restore activity.** Open doc; close activity. ActivityChip appears. Click → activity returns.
7. **Persist.** Open doc-to-side; hard-reload. Same doc pane restored, focus restored.
8. **Persist with missing session.** Set localStorage to include bogus sessionId chat. Reload → "Session unavailable" placeholder.
9. **Open-already-open.** Click `⇆` twice on same file → focus jumps; no duplicate.
10. **Max panes.** 4th `⇆` shows toast; stack stays at 3.
11. **Focus routing.** Right-column chat pane focused → session-list click routes there, not to centre.
12. **Resize.** Drag inner divider; reload; sizes persist. Add third pane → sizes reset to equal.
13. **Truncated file flag.** Open >256 KiB file → badge in PaneItem header.
14. **Binary file.** Binary preview not available.

### Automated
- `useRightPanes.test.js` — open/close/restore-activity/focus, persistence round-trip, hydration with corrupt JSON, dedup.
- `PaneItem.test.js` — close/focus/keyboard a11y, title truncation, `headerAccessory` slot.
- `FileTreePanel.test.js` — `⇆` visible on hover, calls `openDocToSide` with correct `{path, scope}`; Shift+Enter.
- `FileViewer.test.js` — `embedded` hides `.fv-header`.

### Regression
- Centre column "split chats side-by-side" still works.
- `SessionEventsProvider` opens exactly one SSE connection.
- `mode` toggle still hides/shows right column.

---

## 12. Sequencing and dependencies

1. **Block:** `<ResizableSplit>` must land first.
2. **Block:** `<FileTreePanel>` + `<FileViewer>` must land first.
3. Ship order:
   a. `PaneItem` + CSS
   b. `useRightPanes` + `RightPaneContext`
   c. `FileViewer.embedded` patch
   d. `DashboardControlCenter.js` integration
   e. `FileTreePanel` `⇆` button + Shift+Enter
   f. `ActivityChip`

(b) and (d) land together. Single squashed PR per CI-build-discipline.

---

## 13. Risks and trade-offs

- **`<ResizableSplit>` API unknown.** Only step (10.5) changes if API differs; rest decoupled.
- **Re-keying on pane add/remove resets widths.** Acceptable for v1. Post-v1 could persist `sizes` keyed by pane-id signature.
- **Focus routing complexity (`lastFocusedColumn`).** Isolated in `useRightPanes` + existing centre-column handler.
- **Activity chip on Simple mode.** Intentionally not shown. Follow-up if users expect.
- **localStorage corruption.** Mitigated by hydrate-fallback + console.warn.

---

## Critical files

- `apps/web/src/pages/DashboardControlCenter.js`
- `apps/web/src/dashboard/FileTreePanel.js`
- `apps/web/src/dashboard/FileViewer.js`
- `apps/web/src/dashboard/AgentActivityPanel.js`
- `apps/web/src/dashboard/tabs/ChatTab.js`
