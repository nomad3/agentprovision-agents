/*
 * useV2SessionEvents — subscribe to /api/v2/sessions/{id}/events SSE stream.
 *
 * Uses fetch + ReadableStream rather than EventSource so we can send the
 * Authorization: Bearer header (deps.get_current_active_user requires
 * it; EventSource cannot set custom headers).
 *
 * Envelope shape (per design §5):
 *   { event_id, session_id, tenant_id, ts, seq_no, type, payload }
 *
 * Behavior:
 * - Tracks last seen `seq_no` in a ref so reconnects request only
 *   missed events via `?since=<seq>`.
 * - Auto-reconnects with exponential backoff (1s, 2s, 4s, capped 30s)
 *   when the stream ends unexpectedly. Backend never closes a healthy
 *   stream — a clean EOF means a proxy timeout / network blip and
 *   we should resume.
 * - Dedupes by event_id (or `seq:${seq_no}` if event_id is missing);
 *   skips frames that lack both. The dedupe set is rebuilt from the
 *   live event window whenever the window is trimmed, so it never
 *   grows unbounded over long sessions.
 *
 * Status values (consumed by AgentActivityPanel for the indicator):
 *   idle          — no session bound
 *   connecting    — first connection attempt in flight
 *   open          — receiving events
 *   reconnecting  — stream dropped, backoff timer running
 *   error         — non-recoverable (caller should investigate)
 *   unauthorized  — no JWT in localStorage / 401 from server
 */
import { useEffect, useRef, useState } from 'react';

const MAX_EVENTS = 200;
const API_BASE = process.env.REACT_APP_API_URL || '';
const BACKOFF_START_MS = 1000;
const BACKOFF_MAX_MS = 30_000;

const _getToken = () => {
  try { return localStorage.getItem('token') || ''; } catch { return ''; }
};

const _idFor = (env) => env.event_id || (env.seq_no != null ? `seq:${env.seq_no}` : null);

export const useV2SessionEvents = (sessionId) => {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState('idle');
  const seenIds = useRef(new Set());
  const lastSeqNo = useRef(null);

  useEffect(() => {
    seenIds.current = new Set();
    lastSeqNo.current = null;
    setEvents([]);

    if (!sessionId) {
      setStatus('idle');
      return undefined;
    }

    let cancelled = false;
    let ctrl = null;
    let backoffTimer = null;
    let backoffMs = BACKOFF_START_MS;

    const connect = async () => {
      if (cancelled) return;
      const token = _getToken();
      if (!token) {
        if (cancelled) return;
        setStatus('unauthorized');
        return;
      }
      ctrl = new AbortController();
      if (cancelled) return;
      setStatus((prev) => (prev === 'open' ? 'reconnecting' : 'connecting'));
      const since = lastSeqNo.current;
      const url = since != null
        ? `${API_BASE}/api/v2/sessions/${sessionId}/events?since=${since}`
        : `${API_BASE}/api/v2/sessions/${sessionId}/events`;
      try {
        const res = await fetch(url, {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'text/event-stream',
          },
          signal: ctrl.signal,
        });
        if (cancelled) return;
        if (!res.ok || !res.body) {
          if (res.status === 401) {
            setStatus('unauthorized');
            return;
          }
          throw new Error(`status=${res.status}`);
        }
        setStatus('open');
        // Reset backoff after a successful handshake.
        backoffMs = BACKOFF_START_MS;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (cancelled) return;
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            let env;
            try { env = JSON.parse(line.slice(6)); } catch { continue; }
            const id = _idFor(env);
            if (!id) continue;
            if (seenIds.current.has(id)) continue;
            seenIds.current.add(id);
            if (typeof env.seq_no === 'number') {
              if (lastSeqNo.current == null || env.seq_no > lastSeqNo.current) {
                lastSeqNo.current = env.seq_no;
              }
            }
            setEvents((prev) => {
              const next = [...prev, env];
              if (next.length > MAX_EVENTS) {
                // Bound dedupe set growth: rebuild it from the trimmed
                // window. Replay events that fall out of the window can
                // arrive again from a reconnect's `since=`, but the
                // server-side seq_no monotonicity already guards that —
                // we only reset the *dedupe cache* here, not lastSeqNo.
                const trimmed = next.slice(next.length - MAX_EVENTS);
                const rebuilt = new Set();
                for (const e of trimmed) {
                  const eid = _idFor(e);
                  if (eid) rebuilt.add(eid);
                }
                seenIds.current = rebuilt;
                return trimmed;
              }
              return next;
            });
          }
        }
      } catch (err) {
        if (cancelled || err.name === 'AbortError') return;
      }
      if (cancelled) return;
      setStatus('reconnecting');
      const delay = backoffMs;
      backoffMs = Math.min(backoffMs * 2, BACKOFF_MAX_MS);
      backoffTimer = setTimeout(() => {
        if (!cancelled) connect();
      }, delay);
    };

    connect();

    return () => {
      cancelled = true;
      if (ctrl) try { ctrl.abort(); } catch { /* noop */ }
      if (backoffTimer) clearTimeout(backoffTimer);
    };
  }, [sessionId]);

  return { events, status };
};
