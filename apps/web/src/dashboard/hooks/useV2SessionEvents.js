/*
 * useV2SessionEvents — subscribe to /api/v2/sessions/{id}/events SSE stream.
 *
 * Uses fetch + ReadableStream rather than EventSource so we can send the
 * Authorization: Bearer header (deps.get_current_active_user requires
 * it; EventSource cannot set custom headers).
 *
 * Returns the rolling tail of events for a session. Full envelope shape:
 *   { event_id, session_id, tenant_id, ts, seq_no, type, payload }
 *
 * Dedupes by event_id (SSE can replay on reconnect via `since=`).
 * Caps at last 200 events to bound memory.
 */
import { useEffect, useRef, useState } from 'react';

const MAX_EVENTS = 200;
const API_BASE = process.env.REACT_APP_API_URL || '';

const _getToken = () => {
  try { return localStorage.getItem('token') || ''; } catch { return ''; }
};

export const useV2SessionEvents = (sessionId) => {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState('idle');
  const seenIds = useRef(new Set());

  useEffect(() => {
    seenIds.current = new Set();
    setEvents([]);

    if (!sessionId) {
      setStatus('idle');
      return undefined;
    }

    const ctrl = new AbortController();
    setStatus('connecting');

    (async () => {
      const token = _getToken();
      if (!token) {
        setStatus('error');
        return;
      }
      try {
        const res = await fetch(
          `${API_BASE}/api/v2/sessions/${sessionId}/events`,
          {
            headers: {
              Authorization: `Bearer ${token}`,
              Accept: 'text/event-stream',
            },
            signal: ctrl.signal,
          },
        );
        if (!res.ok || !res.body) {
          setStatus('error');
          return;
        }
        setStatus('open');
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const env = JSON.parse(line.slice(6));
              const id = env.event_id || env.seq_no || `${env.ts}-${Math.random()}`;
              if (seenIds.current.has(id)) continue;
              seenIds.current.add(id);
              setEvents((prev) => {
                const next = [...prev, env];
                return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
              });
            } catch {
              // ignore malformed frames
            }
          }
        }
        // Stream closed cleanly (server end). Mark idle so consumer
        // can show a "stream ended" affordance if it wants to.
        setStatus('idle');
      } catch (err) {
        if (err.name === 'AbortError') return;
        setStatus('error');
      }
    })();

    return () => { ctrl.abort(); };
  }, [sessionId]);

  return { events, status };
};
