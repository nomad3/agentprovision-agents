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
 *
 * Full-CLI-stream enhancements (plan
 * docs/plans/2026-05-16-terminal-full-cli-output.md):
 *   - chunk_kind / fd attributes drive per-kind colouring via
 *     TerminalGroup.css. Coalesced replay envelopes ({chunks:[…]})
 *     are spread into per-line entries so colours survive replay.
 *   - MAX_LINES_PER_TAB raised to 1000 — sustained reasoning streams
 *     blow past 200 lines easily.
 *   - Sticky-bottom auto-scroll is per-platform (review I7): switching
 *     tabs preserves the user's read position for each individual
 *     stream rather than yanking back to live tail every tab change.
 */
import { useEffect, useMemo, useRef } from 'react';
import { useSessionEvents } from './SessionEventsContext';
import './TerminalGroup.css';

const MAX_LINES_PER_TAB = 1000;
// Stickiness threshold for "user is at bottom" — within this many px of
// the bottom we keep snapping. Above it we leave the scroll alone so
// the user can read history without the stream yanking them back.
const STICKY_BOTTOM_PX = 24;

// Lifecycle/chunk → per-line conversion. Output is a list of
// `{platform, lines:[{seq, chunk, fd, chunk_kind, ts}]}` so each line
// can carry its kind/fd into the DOM (data-kind / fd attribute) for
// CSS colouring.
const linesFromEvents = (events) => {
  const byPlatform = new Map();
  const pushLine = (platform, line) => {
    const arr = byPlatform.get(platform) || [];
    arr.push(line);
    if (arr.length > MAX_LINES_PER_TAB) {
      arr.splice(0, arr.length - MAX_LINES_PER_TAB);
    }
    byPlatform.set(platform, arr);
  };

  for (const env of events) {
    const type = env.type || env.event_type;
    const pl = env.payload || {};
    const p = pl.platform || 'cli';

    if (type === 'cli_subprocess_stream') {
      // Coalesced replay shape — array of chunk dicts. Spread each
      // into its own line so kind colouring survives replay.
      if (Array.isArray(pl.chunks)) {
        for (const c of pl.chunks) {
          if (!c) continue;
          const chunkStr = typeof c === 'string' ? c : (c.chunk || '');
          if (!chunkStr) continue;
          const kind = (typeof c === 'object' && c.chunk_kind) || pl.chunk_kind || 'stdout';
          const fdv = (typeof c === 'object' && c.fd) || pl.fd || 'stdout';
          const ending = chunkStr.endsWith('\n') ? chunkStr : `${chunkStr}\n`;
          pushLine(p, {
            seq: env.seq_no,
            chunk: ending,
            fd: fdv,
            chunk_kind: kind,
            ts: env.ts,
          });
        }
        continue;
      }
      // Live (non-coalesced) per-chunk event.
      const chunk = pl.chunk || '';
      if (!chunk) continue;
      const kind = pl.chunk_kind || 'stdout';
      const fdv = pl.fd || 'stdout';
      const ending = chunk.endsWith('\n') ? chunk : `${chunk}\n`;
      pushLine(p, {
        seq: env.seq_no,
        chunk: ending,
        fd: fdv,
        chunk_kind: kind,
        ts: env.ts,
      });
    } else if (type === 'cli_subprocess_started') {
      const line = `▶ start ${pl.platform || p}  (attempt ${pl.attempt ?? '?'}/${(pl.chain || []).length || '?'})\n`;
      pushLine(p, {
        seq: env.seq_no,
        chunk: line,
        fd: 'stdout',
        chunk_kind: 'lifecycle',
        ts: env.ts,
      });
    } else if (type === 'cli_subprocess_complete') {
      let line;
      let fd = 'stdout';
      let kind = 'lifecycle';
      if (pl.error) {
        line = `✗ end   ${pl.platform || p}  ${pl.latency_ms ?? '?'}ms — ${pl.error}${pl.error_detail ? ': ' + String(pl.error_detail).slice(0, 100) : ''}\n`;
        fd = 'stderr';
        kind = 'lifecycle_error';
      } else {
        const cost = pl.cost_usd != null ? `  $${Number(pl.cost_usd).toFixed(4)}` : '';
        const tok = pl.token_count != null ? `  ${pl.token_count}tok` : '';
        line = `✓ end   ${pl.platform || p}  ${pl.latency_ms ?? '?'}ms${tok}${cost}\n`;
      }
      pushLine(p, { seq: env.seq_no, chunk: line, fd, chunk_kind: kind, ts: env.ts });
    }
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
  // Per-platform sticky-to-bottom map (review I7). Keyed by platform
  // name; absent entries default to "true" (follow tail) so the very
  // first chunk autoscrolls without requiring an initialisation pass.
  // Stored in a ref so the scroll handler can update without forcing
  // a re-render.
  const stuckToBottomRef = useRef({});

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

  // Auto-scroll to bottom on new chunks, but only when this platform's
  // sticky flag is true. Switching to a new tab preserves the previous
  // tab's sticky state — when you come back, you're still where you
  // left off.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (!activeTabKey) return;
    // Default to "follow tail" the first time we see a platform.
    if (stuckToBottomRef.current[activeTabKey] !== false) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events, activeTabKey]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || !activeTabKey) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    stuckToBottomRef.current[activeTabKey] = dist <= STICKY_BOTTOM_PX;
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
                    data-kind={line.chunk_kind || 'stdout'}
                    data-fd={line.fd || 'stdout'}
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
