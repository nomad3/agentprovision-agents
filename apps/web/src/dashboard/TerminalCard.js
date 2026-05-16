/*
 * TerminalCard — Phase 2 live terminal output.
 *
 * Subscribes to the same v2 SSE feed as AgentActivityPanel but filters to
 * `cli_subprocess_stream` events (stdout/stderr chunks emitted by the
 * cloud CLI workers — claude_code / codex / gemini_cli / copilot_cli).
 * Renders them per-platform as a multi-tab monospace stream so the user
 * can watch the kernel work in real time.
 *
 * Phase 2 design doc: docs/plans/2026-05-15-alpha-control-center-phase-2-design.md
 *
 * Phase 2 v1 keeps it simple: <pre> with auto-scroll, plain text (no
 * ANSI escape parsing yet — most CLI workers emit plain chunks via the
 * orchestrator's pre-processing). xterm.js upgrade is Phase 2.5.
 *
 * The card lives in the DashboardControlCenter below the chat row,
 * collapsed by default with a "Show terminal" toggle and auto-shows
 * the first time a `cli_subprocess_stream` event arrives for the
 * current session.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { FaTerminal, FaChevronDown, FaChevronRight } from 'react-icons/fa';
import { useSessionEvents } from './SessionEventsContext';
import './TerminalCard.css';

const MAX_LINES_PER_TAB = 500;

const TerminalCard = ({ sessionId }) => {
  const { events, status } = useSessionEvents();
  const [open, setOpen] = useState(false);
  const [activePlatform, setActivePlatform] = useState(null);
  const [autoOpened, setAutoOpened] = useState(false);
  const scrollRef = useRef(null);

  // Group cli_subprocess_stream events by platform. Each platform gets
  // its own tab with a tail-only window (last N chunks).
  const streams = useMemo(() => {
    const byPlatform = new Map();
    for (const env of events) {
      const type = env.type || env.event_type;
      if (type !== 'cli_subprocess_stream') continue;
      const p = (env.payload || {}).platform || 'cli';
      const chunk = (env.payload || {}).chunk || '';
      const arr = byPlatform.get(p) || [];
      arr.push({
        seq: env.seq_no,
        chunk,
        fd: (env.payload || {}).fd || 'stdout',
        ts: env.ts,
      });
      if (arr.length > MAX_LINES_PER_TAB) {
        arr.splice(0, arr.length - MAX_LINES_PER_TAB);
      }
      byPlatform.set(p, arr);
    }
    return Array.from(byPlatform.entries()).map(([platform, lines]) => ({ platform, lines }));
  }, [events]);

  // Auto-open + select first platform when the first chunk arrives.
  useEffect(() => {
    if (autoOpened || streams.length === 0) return;
    setOpen(true);
    setActivePlatform(streams[0].platform);
    setAutoOpened(true);
  }, [streams, autoOpened]);

  // Make sure activePlatform stays valid if the active stream goes away.
  useEffect(() => {
    if (!activePlatform && streams.length > 0) {
      setActivePlatform(streams[0].platform);
    } else if (activePlatform && !streams.find((s) => s.platform === activePlatform)) {
      setActivePlatform(streams[0]?.platform || null);
    }
  }, [streams, activePlatform]);

  // Auto-scroll to bottom on new chunks.
  useEffect(() => {
    if (!open || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events, activePlatform, open]);

  const activeStream = streams.find((s) => s.platform === activePlatform);
  const totalChunks = streams.reduce((acc, s) => acc + s.lines.length, 0);

  return (
    <article className={`ap-card tc-card${open ? ' open' : ''}`}>
      <button
        type="button"
        className="tc-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="tc-header-left">
          {open ? <FaChevronDown size={11} /> : <FaChevronRight size={11} />}
          <FaTerminal size={13} className="tc-header-icon" />
          <span className="tc-header-title">Terminal</span>
          {totalChunks > 0 && (
            <span className="tc-header-badge">{totalChunks} lines · {streams.length} stream{streams.length === 1 ? '' : 's'}</span>
          )}
        </span>
        <span className={`tc-header-status tc-header-status-${status}`}>
          {status === 'open' ? '● live'
            : status === 'reconnecting' ? '⟳ reconnecting'
            : status === 'unauthorized' ? '⚠ signed out'
            : status === 'connecting' ? '○ connecting'
            : '○ idle'}
        </span>
      </button>

      {open && (
        <div className="tc-body">
          {streams.length === 0 ? (
            <div className="tc-empty">
              {sessionId
                ? 'No CLI subprocess output yet for this session. Output appears here when alpha runs claude_code, codex, gemini_cli, or copilot_cli.'
                : 'Open a chat session to see CLI output.'}
            </div>
          ) : (
            <>
              <div className="tc-tabs" role="tablist">
                {streams.map(({ platform, lines }) => (
                  <button
                    key={platform}
                    type="button"
                    role="tab"
                    aria-selected={activePlatform === platform}
                    className={`tc-tab${activePlatform === platform ? ' active' : ''}`}
                    onClick={() => setActivePlatform(platform)}
                  >
                    <span className="tc-tab-platform">{platform}</span>
                    <span className="tc-tab-count">{lines.length}</span>
                  </button>
                ))}
              </div>
              <div className="tc-stream" ref={scrollRef}>
                {activeStream ? (
                  <pre className="tc-pre">
                    {activeStream.lines.map((line, idx) => (
                      <span
                        key={`${line.seq}-${idx}`}
                        className={`tc-line${line.fd === 'stderr' ? ' stderr' : ''}`}
                      >
                        {line.chunk}
                      </span>
                    ))}
                  </pre>
                ) : (
                  <div className="tc-empty">Select a stream to view output.</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </article>
  );
};

export default TerminalCard;
