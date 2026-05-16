/*
 * TerminalGroup — a single VSCode-style terminal "group" inside the
 * multi-pane terminal panel. Wraps:
 *
 *   ┌── tab strip (one tab per CLI platform discovered in the stream) ──┐
 *   │  claude_code  codex  gemini_cli  …                                 │
 *   ├──────────────────────────────────────────────────────────────────┤
 *   │ <pre> chunk render with sticky-bottom auto-scroll                 │
 *   └──────────────────────────────────────────────────────────────────┘
 *
 * Extracted from the previous monolithic TerminalCard. The owning
 * <TerminalPanel> can host up to four of these side-by-side inside an
 * inner row-direction <ResizableSplit>. Each group runs its own
 * `useMemo` filter over the shared `events` array from
 * useSessionEvents(), so per-group state (active tab) is local but the
 * SSE subscription is still single-shared.
 *
 * Focus indicator (`.tg-card-focused`) mirrors `.dcc-thread-card-focused`
 * from the chat editor-groups pattern — 2 px inset brand-primary border
 * so layout doesn't shift on focus change. PointerDownCapture shifts
 * focus before any inner click handler runs (matches
 * DashboardControlCenter.js around line 79).
 */
import { useEffect, useMemo, useRef } from 'react';
import { useSessionEvents } from './SessionEventsContext';
import './TerminalGroup.css';

const MAX_LINES_PER_TAB = 1000;
// Stickiness threshold for "user is at bottom" — within this many px of
// the bottom we keep snapping. Above it we leave the scroll alone so
// the user can read history without the stream yanking them back.
const STICKY_BOTTOM_PX = 24;

// Reuse the same lifecycle/chunk → line conversion that TerminalCard
// used pre-refactor. Kept verbatim so the parallel CLI-streaming branch
// (#240) can replay its rendering enhancements onto this function with
// a mechanical merge.
const linesFromEvents = (events) => {
  const byPlatform = new Map();
  for (const env of events) {
    const type = env.type || env.event_type;
    const p = (env.payload || {}).platform || 'cli';
    let line = null;
    let fd = 'stdout';
    if (type === 'cli_subprocess_stream') {
      line = (env.payload || {}).chunk || '';
      fd = (env.payload || {}).fd || 'stdout';
    } else if (type === 'cli_subprocess_started') {
      const pl = env.payload || {};
      line = `▶ start ${pl.platform || p}  (attempt ${pl.attempt ?? '?'}/${(pl.chain || []).length || '?'})`;
    } else if (type === 'cli_subprocess_complete') {
      const pl = env.payload || {};
      if (pl.error) {
        line = `✗ end   ${pl.platform || p}  ${pl.latency_ms ?? '?'}ms — ${pl.error}${pl.error_detail ? ': ' + String(pl.error_detail).slice(0, 100) : ''}`;
        fd = 'stderr';
      } else {
        const cost = pl.cost_usd != null ? `  $${Number(pl.cost_usd).toFixed(4)}` : '';
        const tok = pl.token_count != null ? `  ${pl.token_count}tok` : '';
        line = `✓ end   ${pl.platform || p}  ${pl.latency_ms ?? '?'}ms${tok}${cost}`;
      }
    } else {
      continue;
    }
    if (!line) continue;
    if (!line.endsWith('\n')) line += '\n';
    const arr = byPlatform.get(p) || [];
    arr.push({ seq: env.seq_no, chunk: line, fd, ts: env.ts });
    if (arr.length > MAX_LINES_PER_TAB) {
      arr.splice(0, arr.length - MAX_LINES_PER_TAB);
    }
    byPlatform.set(p, arr);
  }
  return Array.from(byPlatform.entries()).map(([platform, lines]) => ({ platform, lines }));
};

const TerminalGroup = ({
  groupId,
  sessionId,
  activeTabKey,
  focused,
  onActiveChange,
  onFocus,
}) => {
  const { events } = useSessionEvents();
  const scrollRef = useRef(null);
  // Track whether the user is "stuck to bottom" so we only auto-snap
  // when they haven't scrolled up to read history.
  const stuckToBottomRef = useRef(true);

  const streams = useMemo(() => linesFromEvents(events), [events]);

  // Keep activeTabKey valid when streams come and go. Owner (TerminalPanel)
  // holds the canonical value; we just nudge it via onActiveChange when
  // the current one becomes invalid or there's nothing selected yet.
  useEffect(() => {
    if (!streams.length) return;
    if (!activeTabKey) {
      onActiveChange?.(streams[0].platform);
      return;
    }
    if (!streams.find((s) => s.platform === activeTabKey)) {
      onActiveChange?.(streams[0].platform);
    }
  }, [streams, activeTabKey, onActiveChange]);

  // Auto-scroll to bottom on new chunks, but only when we were already
  // pinned to bottom. Without this guard, reading historical output
  // would get yanked away every time a new line arrives.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stuckToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events, activeTabKey]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    stuckToBottomRef.current = dist <= STICKY_BOTTOM_PX;
  };

  const activeStream = streams.find((s) => s.platform === activeTabKey);

  return (
    <article
      className={`ap-card tg-card${focused ? ' tg-card-focused' : ''}`}
      data-group-id={groupId}
      onPointerDownCapture={() => {
        // PointerDown-capture so focus shifts BEFORE any inner click
        // handler (tab button, scroll-area click) runs. Same pattern as
        // chat editor groups in DashboardControlCenter.
        onFocus?.();
      }}
      onFocusCapture={() => {
        // Tab into any focusable child also lifts the group's focus,
        // so keyboard users can move between groups without first
        // clicking. Mirrors the editor-groups pattern.
        onFocus?.();
      }}
    >
      {streams.length === 0 ? (
        <div className="tg-empty">
          {sessionId
            ? 'No CLI subprocess output yet for this session. Output appears here when alpha runs claude_code, codex, gemini_cli, or copilot_cli.'
            : 'Open a chat session to see CLI output.'}
        </div>
      ) : (
        <>
          <div className="tg-tabs" role="tablist">
            {streams.map(({ platform, lines }) => (
              <button
                key={platform}
                type="button"
                role="tab"
                aria-selected={activeTabKey === platform}
                className={`tg-tab${activeTabKey === platform ? ' active' : ''}`}
                onClick={() => onActiveChange?.(platform)}
              >
                <span className="tg-tab-platform">{platform}</span>
                <span className="tg-tab-count">{lines.length}</span>
              </button>
            ))}
          </div>
          <div className="tg-stream" ref={scrollRef} onScroll={onScroll}>
            {activeStream ? (
              <pre className="tg-pre">
                {activeStream.lines.map((line, idx) => (
                  <span
                    key={`${line.seq}-${idx}`}
                    className={`tg-line${line.fd === 'stderr' ? ' stderr' : ''}`}
                  >
                    {line.chunk}
                  </span>
                ))}
              </pre>
            ) : (
              <div className="tg-empty">Select a stream to view output.</div>
            )}
          </div>
        </>
      )}
    </article>
  );
};

export default TerminalGroup;
