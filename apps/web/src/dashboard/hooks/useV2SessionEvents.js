/*
 * useV2SessionEvents — subscribe to /api/v2/sessions/{id}/events SSE stream.
 *
 * Returns the rolling tail of events for a session. The full envelope shape
 * is the one described in the Alpha Control Plane design doc §5:
 *   { event_id, session_id, tenant_id, ts, seq_no, type, payload }
 *
 * Dedupes by event_id (events can arrive twice if the SSE reconnects and
 * the server replays from `since=`).
 *
 * Cap: keeps the last 200 events to bound memory; AgentActivityPanel
 * doesn't need more for the live view.
 */
import { useEffect, useRef, useState } from 'react';

const MAX_EVENTS = 200;
const API_BASE = process.env.REACT_APP_API_URL || '';

export const useV2SessionEvents = (sessionId) => {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | connecting | open | error
  const seenIds = useRef(new Set());

  useEffect(() => {
    seenIds.current = new Set();
    setEvents([]);

    if (!sessionId) {
      setStatus('idle');
      return undefined;
    }

    setStatus('connecting');

    // EventSource doesn't support custom headers — auth token rides as
    // a query param so the SSE handshake authenticates without a
    // preflight. The backend's deps.get_current_active_user reads it.
    const token = (() => { try { return localStorage.getItem('token') || ''; } catch { return ''; } })();
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : '';
    const url = `${API_BASE}/api/v2/sessions/${sessionId}/events${qs}`;
    const es = new EventSource(url, { withCredentials: false });

    es.onopen = () => setStatus('open');
    es.onerror = () => {
      // EventSource auto-reconnects; the status flips to 'error' so the
      // status bar can show degraded connectivity until it recovers.
      setStatus('error');
    };
    es.onmessage = (msg) => {
      try {
        const env = JSON.parse(msg.data);
        const id = env.event_id || env.seq_no || `${env.ts}-${Math.random()}`;
        if (seenIds.current.has(id)) return;
        seenIds.current.add(id);
        setEvents((prev) => {
          const next = [...prev, env];
          return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
        });
      } catch {
        // Ignore malformed frames rather than tearing the stream.
      }
    };

    return () => {
      try { es.close(); } catch { /* noop */ }
      setStatus('idle');
    };
  }, [sessionId]);

  return { events, status };
};
