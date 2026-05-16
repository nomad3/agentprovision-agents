/*
 * TerminalPanel — VSCode-style multi-pane terminal panel.
 *
 * Owns:
 *  - N (1..MAX_GROUPS) terminal groups laid out side-by-side via an
 *    inner row-direction <ResizableSplit>.
 *  - The header strip (collapse toggle, title, status badge, group +
 *    line counts, split-column button, close-focused-group button).
 *  - Collapse state (`apControl.terminalOpen`), groups state
 *    (`apControl.terminalGroups`), focused-group id
 *    (`apControl.terminalFocusedGroupId`) — all persisted to
 *    localStorage so layout survives navigation and reload.
 *  - Auto-open-on-first-chunk: when a `cli_subprocess_stream` event
 *    arrives and the panel is collapsed, open the panel and surface
 *    the chunk's platform as the focused group's active tab.
 *  - Mobile fallback (<992 px): single focused group only — stacking
 *    multiple groups vertically would be worse than tabs anyway, and
 *    the inner ResizableSplit's stacked mode already collapses
 *    handles below the breakpoint.
 *
 * The previous monolithic `TerminalCard` has been split into:
 *   <TerminalPanel> (this file) → owns chrome + layout + lifecycle
 *   <TerminalGroup>              → tab strip + <pre> stream
 *   TerminalCard.js              → thin re-export shim
 *
 * Reasoning + sequencing: docs/plans/2026-05-16-terminal-vscode-style-redesign.md
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FaTerminal, FaChevronDown, FaChevronRight, FaColumns, FaTimes } from 'react-icons/fa';
import { useSessionEvents } from './SessionEventsContext';
import ResizableSplit from './ResizableSplit';
import TerminalGroup from './TerminalGroup';
import './TerminalPanel.css';

const MAX_GROUPS = 4;
const MOBILE_BREAKPOINT = 992;

// ── localStorage keys (net-new namespaces — no migration needed) ──
const LS_GROUPS = 'apControl.terminalGroups';
const LS_FOCUSED = 'apControl.terminalFocusedGroupId';
const LS_OPEN = 'apControl.terminalOpen';

const DEFAULT_GROUPS = [{ id: 'tg-1', activeTabKey: null }];

const safeReadGroups = () => {
  if (typeof window === 'undefined') return DEFAULT_GROUPS;
  try {
    const raw = window.localStorage.getItem(LS_GROUPS);
    if (!raw) return DEFAULT_GROUPS;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return DEFAULT_GROUPS;
    const clean = parsed
      .filter((g) => g && typeof g.id === 'string')
      .slice(0, MAX_GROUPS)
      .map((g) => ({
        id: g.id,
        activeTabKey: typeof g.activeTabKey === 'string' ? g.activeTabKey : null,
      }));
    return clean.length ? clean : DEFAULT_GROUPS;
  } catch {
    return DEFAULT_GROUPS;
  }
};

const safeReadFocused = (groups) => {
  if (typeof window === 'undefined') return groups[0].id;
  try {
    const id = window.localStorage.getItem(LS_FOCUSED);
    if (id && groups.some((g) => g.id === id)) return id;
  } catch { /* fall through */ }
  return groups[0].id;
};

const safeReadOpen = () => {
  if (typeof window === 'undefined') return false;
  try {
    const v = window.localStorage.getItem(LS_OPEN);
    if (v == null) return false;
    return v === 'true';
  } catch { return false; }
};

const writeLs = (key, value) => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* quota / private mode — non-fatal */
  }
};

const useViewportIsMobile = () => {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth < MOBILE_BREAKPOINT;
  });
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return isMobile;
};

// Pure helper — derives per-platform line counts from the shared
// events feed so the header can report `415 lines` without each
// TerminalGroup having to surface its memo. Kept dirt-simple: same
// filter logic as TerminalGroup but only counts, doesn't render. If
// this becomes a hot path we can lift the full streams map into
// TerminalPanel and pass it down.
const countChunks = (events) => {
  let n = 0;
  for (const env of events) {
    const t = env.type || env.event_type;
    if (t === 'cli_subprocess_stream'
        || t === 'cli_subprocess_started'
        || t === 'cli_subprocess_complete') {
      n += 1;
    }
  }
  return n;
};

// First `cli_subprocess_stream` we see for the current event tail —
// used by the auto-open effect to surface the right platform in the
// focused group.
const firstStreamPlatform = (events) => {
  for (const env of events) {
    const t = env.type || env.event_type;
    if (t === 'cli_subprocess_stream') {
      return (env.payload || {}).platform || 'cli';
    }
  }
  return null;
};

const TerminalPanel = ({ sessionId }) => {
  const { events, status } = useSessionEvents();
  const isMobile = useViewportIsMobile();

  const [groups, setGroups] = useState(safeReadGroups);
  const [focusedGroupId, setFocusedGroupId] = useState(() => safeReadFocused(safeReadGroups()));
  const [open, setOpen] = useState(safeReadOpen);
  const autoOpenedRef = useRef(false);

  // ── Persist state to localStorage ──
  useEffect(() => { writeLs(LS_GROUPS, JSON.stringify(groups)); }, [groups]);
  useEffect(() => { writeLs(LS_FOCUSED, focusedGroupId); }, [focusedGroupId]);
  useEffect(() => { writeLs(LS_OPEN, String(open)); }, [open]);

  // Keep focusedGroupId valid when groups change (close-focused-group,
  // localStorage corruption, etc.). Without this, the focused id can
  // dangle and the focus border vanishes entirely.
  useEffect(() => {
    if (!groups.some((g) => g.id === focusedGroupId)) {
      setFocusedGroupId(groups[groups.length - 1]?.id || groups[0]?.id);
    }
  }, [groups, focusedGroupId]);

  // Auto-open on first chunk for this session. Fires once per
  // component mount — after the user explicitly collapses, we don't
  // pop back open on subsequent chunks (matches legacy TerminalCard
  // behaviour).
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (events.length === 0) return;
    const plat = firstStreamPlatform(events);
    if (!plat) return;
    autoOpenedRef.current = true;
    if (!open) setOpen(true);
    // Surface the platform in the focused group's tab if it doesn't
    // already have one — TerminalGroup will pick it up immediately.
    setGroups((cur) => cur.map((g) =>
      g.id === focusedGroupId && !g.activeTabKey
        ? { ...g, activeTabKey: plat }
        : g,
    ));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  const totalChunks = useMemo(() => countChunks(events), [events]);

  // ── Action handlers ──
  const toggleOpen = useCallback(() => setOpen((v) => !v), []);

  const handleSplit = useCallback(() => {
    setGroups((cur) => {
      if (cur.length >= MAX_GROUPS) return cur;
      const focusedIdx = cur.findIndex((g) => g.id === focusedGroupId);
      const idx = focusedIdx < 0 ? cur.length - 1 : focusedIdx;
      const newId = `tg-${Date.now().toString(36)}`;
      const newGroup = { id: newId, activeTabKey: null };
      const next = cur.slice();
      next.splice(idx + 1, 0, newGroup);
      // Focus the freshly-split group so subsequent split/close acts
      // on it (matches VSCode editor-groups behaviour).
      setFocusedGroupId(newId);
      return next;
    });
  }, [focusedGroupId]);

  const handleClose = useCallback(() => {
    setGroups((cur) => {
      if (cur.length <= 1) return cur;
      const idx = cur.findIndex((g) => g.id === focusedGroupId);
      if (idx < 0) return cur;
      const next = cur.filter((g) => g.id !== focusedGroupId);
      const newFocusIdx = Math.max(0, idx - 1);
      setFocusedGroupId(next[newFocusIdx].id);
      return next;
    });
  }, [focusedGroupId]);

  const handleActiveTabChange = useCallback((groupId, platform) => {
    setGroups((cur) => cur.map((g) =>
      g.id === groupId ? { ...g, activeTabKey: platform } : g,
    ));
  }, []);

  const n = groups.length;
  const canSplit = n < MAX_GROUPS && open;
  const canClose = n > 1;

  // Mobile fallback: render only the focused group. Inner
  // ResizableSplit stacking-mode already kicks in below 992 px but
  // stacking N=3 terminal groups vertically is unusable; tabs would
  // be better and this is the cheapest mitigation.
  const focusedIdx = Math.max(0, groups.findIndex((g) => g.id === focusedGroupId));
  const mobileGroup = groups[focusedIdx] || groups[0];

  const renderGroup = (g) => (
    <TerminalGroup
      key={g.id}
      groupId={g.id}
      sessionId={sessionId}
      activeTabKey={g.activeTabKey}
      focused={g.id === focusedGroupId}
      onActiveChange={(plat) => handleActiveTabChange(g.id, plat)}
      onFocus={() => {
        if (focusedGroupId !== g.id) setFocusedGroupId(g.id);
      }}
    />
  );

  return (
    <article className={`ap-card tp-card${open ? ' open' : ''}`}>
      <div className="tp-header">
        <button
          type="button"
          className="tp-header-collapse"
          onClick={toggleOpen}
          aria-expanded={open}
          aria-label={open ? 'Collapse terminal panel' : 'Expand terminal panel'}
        >
          {open ? <FaChevronDown size={11} /> : <FaChevronRight size={11} />}
        </button>
        <FaTerminal size={13} className="tp-header-icon" aria-hidden="true" />
        <span className="tp-header-title">Terminal</span>
        <span className={`tp-header-status tp-header-status-${status}`}>
          {status === 'open' ? '● live'
            : status === 'reconnecting' ? '⟳ reconnecting'
            : status === 'unauthorized' ? '⚠ signed out'
            : status === 'connecting' ? '○ connecting'
            : '○ idle'}
        </span>
        {totalChunks > 0 && (
          <span className="tp-header-badge">
            {n} group{n === 1 ? '' : 's'} · {totalChunks} line{totalChunks === 1 ? '' : 's'}
          </span>
        )}
        <div className="tp-header-actions">
          <button
            type="button"
            className="dcc-thread-iconbtn"
            onClick={handleSplit}
            disabled={!canSplit}
            title={!open ? 'Expand the panel to split'
              : n >= MAX_GROUPS ? `Max ${MAX_GROUPS} groups`
              : 'Split column'}
            aria-label="Split column"
          >
            <FaColumns aria-hidden="true" />
          </button>
          {canClose ? (
            <button
              type="button"
              className="dcc-thread-iconbtn"
              onClick={handleClose}
              title="Close focused group"
              aria-label="Close focused group"
            >
              <FaTimes aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </div>

      {open && (
        <div className="tp-body">
          {isMobile ? (
            // Single-group mobile fallback. We still render through
            // TerminalGroup so the tab strip + auto-scroll behave
            // identically to desktop — just no horizontal split.
            <div className="tp-mobile-single">
              {renderGroup(mobileGroup)}
            </div>
          ) : n === 1 ? (
            <div className="tp-single">{renderGroup(groups[0])}</div>
          ) : (
            <ResizableSplit
              key={`terminal-groups-${n}`}
              storageKey={`dcc.terminalGroups.sizes.${n}`}
              defaultSizes={Array.from({ length: n }, () => 100 / n)}
              minSizes={Array.from({ length: n }, () => 200)}
            >
              {groups.map((g) => renderGroup(g))}
            </ResizableSplit>
          )}
        </div>
      )}
    </article>
  );
};

export default TerminalPanel;
