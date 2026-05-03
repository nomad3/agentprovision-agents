/*
 * LiveActivityFeed — Tier 4 of the visibility roadmap.
 *
 * Rolling tail of the last 5 minutes of agent activity on the
 * dashboard. Polls `GET /audit/agents` (already shipped — it's
 * the same endpoint the Audit tabs use, just sliced to "recent")
 * and renders one row per audit event with relative-time + cost.
 *
 * Top-of-dashboard surface for "what just happened in my tenant".
 * Pure read-only; no SSE for V1 (keeps deps + complexity down — A2A
 * has Redis pub/sub but that's a heavier add than this view needs).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Spinner } from 'react-bootstrap';
import {
  FaCheckCircle,
  FaExchangeAlt,
  FaPause,
  FaPlay,
  FaTimesCircle,
} from 'react-icons/fa';

import api from '../../services/api';
import './LiveActivityFeed.css';


// Polling cadence. 15s gives a "live enough" feel without hammering
// the audit endpoint. Pause toggle lets users freeze the tail when
// they're reading a row (avoid the "scroll-up-and-it-jumps-back" UX).
const POLL_INTERVAL_MS = 15_000;

// How far back to look. 5 minutes matches the plan's "what happened
// recently" wording. Shorter than 5m and a slow tenant looks empty;
// longer and the feed clutters with stale rows.
const LOOKBACK_MS = 5 * 60_000;


function _relativeTime(iso) {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 5_000) return 'just now';
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s ago`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m ago`;
  return `${Math.floor(ms / 3600_000)}h ago`;
}


function _statusBadge(status) {
  if (status === 'success') {
    return (
      <Badge bg="success" pill style={{ fontSize: '0.6rem' }}>
        <FaCheckCircle size={9} className="me-1" /> ok
      </Badge>
    );
  }
  if (status === 'error' || status === 'timeout') {
    return (
      <Badge bg="danger" pill style={{ fontSize: '0.6rem' }}>
        <FaTimesCircle size={9} className="me-1" /> {status}
      </Badge>
    );
  }
  return (
    <Badge bg="secondary" pill style={{ fontSize: '0.6rem' }}>
      {status}
    </Badge>
  );
}


function _costLabel(usd) {
  if (typeof usd !== 'number' || usd <= 0) return null;
  // Same 4-decimal precision as the routing footer (PR #256) so
  // single-turn costs of $0.01–$0.05 don't show as $0.00.
  return `$${usd.toFixed(4)}`;
}


const LiveActivityFeed = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [paused, setPaused] = useState(false);

  const fetchRecent = useCallback(async () => {
    try {
      const fromDt = new Date(Date.now() - LOOKBACK_MS).toISOString();
      const resp = await api.get('/audit/agents', {
        params: { from_dt: fromDt, limit: 25 },
      });
      setRows(resp.data || []);
      setError(null);
    } catch (err) {
      // Audit endpoint requires superuser — non-admin users see this
      // component but the API returns 403. Render a friendly note
      // instead of an error toast (the dashboard isn't broken; this
      // surface just isn't theirs).
      const status = err.response?.status;
      if (status === 403) {
        setError('admin-only');
      } else {
        setError(err.response?.data?.detail || 'Failed to load recent activity.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load — fires exactly once on mount.
  useEffect(() => { fetchRecent(); }, [fetchRecent]);

  // Polling timer — separate effect so toggling `paused` only changes
  // the interval, not the load count. Was previously combined and
  // every pause-click triggered an extra fetch (off-by-one in tests).
  useEffect(() => {
    if (paused) return undefined;
    const id = setInterval(fetchRecent, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchRecent, paused]);

  const togglePause = () => setPaused((p) => !p);

  // Don't render the component at all for non-admin users — the
  // surface depends on /audit/agents which is admin-gated. Better
  // hidden than showing "admin-only" placeholders to every member.
  if (error === 'admin-only') return null;

  return (
    <article className="ap-card live-activity-feed">
      <div className="ap-card-body">
        <div className="d-flex align-items-center justify-content-between mb-2">
          <h6 className="mb-0">
            <span className="live-pulse" aria-hidden="true" /> Live activity
          </h6>
          <button
            type="button"
            onClick={togglePause}
            className="ap-btn-ghost ap-btn-sm"
            title={paused ? 'Resume polling' : 'Pause polling'}
            aria-label={paused ? 'Resume polling' : 'Pause polling'}
          >
            {paused ? <FaPlay size={11} /> : <FaPause size={11} />}
            <span className="ms-1" style={{ fontSize: '0.75rem' }}>
              {paused ? 'Paused' : `Live · ${POLL_INTERVAL_MS / 1000}s`}
            </span>
          </button>
        </div>

        {loading ? (
          <div className="text-center py-3">
            <Spinner animation="border" size="sm" variant="primary" />
          </div>
        ) : error ? (
          <Alert variant="warning" className="py-2 mb-0" style={{ fontSize: '0.85rem' }}>
            {error}
          </Alert>
        ) : !rows.length ? (
          <p className="text-muted mb-0" style={{ fontSize: '0.85rem' }}>
            No agent activity in the last 5 minutes.
          </p>
        ) : (
          <ul className="live-activity-list">
            {rows.map((r) => (
              <li key={r.id} className="live-activity-row">
                <span className="live-activity-time" title={r.created_at}>
                  {_relativeTime(r.created_at)}
                </span>
                <span className="live-activity-summary">
                  <code>{r.invocation_type || 'invoked'}</code>
                  {r.input_summary && (
                    <span className="live-activity-input">
                      {' '}— {r.input_summary.slice(0, 80)}
                      {r.input_summary.length > 80 ? '…' : ''}
                    </span>
                  )}
                </span>
                <span className="live-activity-meta">
                  {r.latency_ms && <span>{r.latency_ms}ms</span>}
                  {_costLabel(r.cost_usd) && <span>{_costLabel(r.cost_usd)}</span>}
                  {_statusBadge(r.status)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
};

export default LiveActivityFeed;
