/*
 * AgentActivityPanel — live A2A + tool-call timeline for the active
 * session, plus pinned context.
 *
 * Subscribes to /api/v2/sessions/{id}/events. Renders one row per event;
 * groups consecutive subagent events under their dispatcher. The CLI
 * orchestrator (kernel) emits these events; this panel is the channel
 * viewport.
 *
 * Replaces the static "Propose / Critique / Revise" stepper from the
 * old CollaborationPanel — that one was always-empty when no coalition
 * was running, which read as "broken". This panel always has something
 * live to show while a session is open.
 */
import {
  FaBolt,
  FaComment,
  FaCog,
  FaArrowRight,
  FaDatabase,
  FaTerminal,
  FaStar,
} from 'react-icons/fa';
import { useSessionEvents } from './SessionEventsContext';
import './AgentActivityPanel.css';

const ICON_FOR_TYPE = {
  chat_message: FaComment,
  tool_call_started: FaCog,
  tool_call_complete: FaCog,
  plan_step_changed: FaArrowRight,
  subagent_dispatched: FaBolt,
  subagent_response: FaBolt,
  cli_subprocess_stream: FaTerminal,
  resource_referenced: FaDatabase,
  auto_quality_score: FaStar,
  auto_quality_consensus: FaStar,
  cli_routing_decision: FaArrowRight,
  cli_subprocess_started: FaTerminal,
  cli_subprocess_complete: FaTerminal,
};

const renderLine = (env) => {
  const t = env.type || env.event_type;
  const p = env.payload || {};
  switch (t) {
    case 'chat_message':
      return `${p.role || 'msg'}: ${(p.text || p.content || '').slice(0, 120)}`;
    case 'tool_call_started':
      return `→ ${p.tool_name || p.tool || 'tool'}`;
    case 'tool_call_complete':
      return `✓ ${p.tool_name || p.tool || 'tool'} ${p.latency_ms ? `(${p.latency_ms}ms)` : ''}${p.error ? ' — error' : ''}`;
    case 'plan_step_changed':
      return `[${p.step_index ?? '?'}] ${p.label || ''} · ${p.status || ''}`;
    case 'subagent_dispatched':
      return `dispatch → ${p.agent_id || p.role || 'peer'}`;
    case 'subagent_response':
      return `${p.agent_id || 'peer'}: ${(p.text || '').slice(0, 100)}`;
    case 'cli_subprocess_stream':
      return `${p.platform || 'cli'}: ${(p.chunk || '').slice(0, 100)}`;
    case 'cli_subprocess_started':
      return `▶ ${p.platform || 'cli'} (attempt ${p.attempt ?? '?'})`;
    case 'cli_subprocess_complete': {
      const tail = p.error
        ? `${p.latency_ms ?? '?'}ms · ${p.error}`
        : `${p.latency_ms ?? '?'}ms${p.token_count != null ? ' · ' + p.token_count + 'tok' : ''}${p.cost_usd != null ? ' · $' + Number(p.cost_usd).toFixed(4) : ''}`;
      return `${p.error ? '✗' : '✓'} ${p.platform || 'cli'} (${tail})`;
    }
    case 'cli_routing_decision': {
      const served = p.served_by || 'none';
      const attempted = (p.attempted || []).join(' → ');
      const tail = p.total_latency_ms != null ? ` · ${p.total_latency_ms}ms` : '';
      return `routed → ${served}  [${attempted || 'no chain'}]${tail}`;
    }
    case 'auto_quality_consensus':
      return `score ${p.adjusted_score ?? p.score}/100 · ${p.consensus_passed ? '✓' : '✗'} ${p.approved_count}/${p.total_reviewers} reviewers · reward ${p.reward}`;
    case 'resource_referenced':
      return `${p.kind || 'ref'} ${p.resource_type || ''}:${p.resource_id || ''}`;
    case 'auto_quality_score':
      return `score ${p.score} · consensus ${p.consensus ?? '—'}`;
    default:
      // Legacy event types from PR #481-#486 era flow through the same
      // pipe with their original `event_type` field; show them as-is.
      return t;
  }
};

const AgentActivityPanel = ({ collapsed, sessionId }) => {
  // events/status come from the shared SessionEventsProvider in
  // DashboardControlCenter — one SSE connection per session, not one
  // per consumer.
  const { events, status } = useSessionEvents();

  if (collapsed) return <div className="ap-right" aria-hidden="true" />;

  return (
    <div className="ap-right">
      <div className="ap-right-header">
        <span className="ap-right-title">Agent activity</span>
        <span className={`ap-right-status ap-right-status-${status}`}>
          {status === 'open' ? '● live'
            : status === 'connecting' ? '○ connecting'
            : status === 'reconnecting' ? '⟳ reconnecting'
            : status === 'unauthorized' ? '⚠ sign in to see activity'
            : status === 'error' ? '⚠ error'
            : '○ idle'}
        </span>
      </div>
      {!sessionId ? (
        <div className="ap-right-empty">Open a chat session to see activity.</div>
      ) : status === 'unauthorized' ? (
        <div className="ap-right-empty">Your session expired. Sign in again to see live activity.</div>
      ) : status === 'error' ? (
        <div className="ap-right-empty">Couldn’t connect to the event stream.</div>
      ) : events.length === 0 && status === 'open' ? (
        <div className="ap-right-empty">No events yet for this session.</div>
      ) : events.length === 0 && status === 'reconnecting' ? (
        <div className="ap-right-empty">Reconnecting…</div>
      ) : events.length === 0 ? (
        <div className="ap-right-empty">Connecting…</div>
      ) : (
        <ul className="ap-right-list">
          {events.slice().reverse().map((env) => {
            const t = env.type || env.event_type;
            const Icon = ICON_FOR_TYPE[t] || FaBolt;
            const ts = env.ts ? new Date(env.ts).toLocaleTimeString() : '';
            return (
              <li key={env.event_id || `seq:${env.seq_no}`} className="ap-right-row">
                <Icon className="ap-right-row-icon" size={11} />
                <div className="ap-right-row-body">
                  <div className="ap-right-row-line">{renderLine(env)}</div>
                  <div className="ap-right-row-meta">
                    {t} · {ts}{env.seq_no != null ? ` · #${env.seq_no}` : ''}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default AgentActivityPanel;
