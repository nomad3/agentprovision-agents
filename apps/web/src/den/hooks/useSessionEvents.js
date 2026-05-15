import { useEffect, useReducer } from 'react';

import api from '../../utils/api';

/**
 * Subscribe to /api/v2/sessions/{id}/events for live + replay.
 *
 * Returns { messages, allEvents } — `messages` is the chat_message
 * subset (the conversation view). `allEvents` is the raw stream
 * (tier 2+ consumers will use this for plan stepper, tool calls,
 * subagent dispatches, etc.).
 *
 * Tier 0–1 only renders messages; this hook still subscribes to the
 * full stream so the den doesn't have to re-mount the SSE on tier
 * promotion.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §5
 */

function reduce(state, action) {
  if (action.type === 'replace') {
    return { messages: action.messages, allEvents: action.events };
  }
  if (action.type === 'append') {
    const evt = action.event;
    if (!evt || !evt.event_id) return state;
    // Dedupe by event_id (multi-channel echo guard, design §5.3)
    if (state.allEvents.some((e) => e.event_id === evt.event_id)) return state;
    const allEvents = [...state.allEvents, evt];
    const messages = evt.type === 'chat_message'
      ? [...state.messages, mapMessage(evt)]
      : state.messages;
    return { messages, allEvents };
  }
  return state;
}

function mapMessage(evt) {
  return {
    event_id: evt.event_id,
    role: evt.payload?.role || 'alpha',
    text: evt.payload?.text || '',
  };
}

export function useSessionEvents(sessionId) {
  const [state, dispatch] = useReducer(reduce, { messages: [], allEvents: [] });

  useEffect(() => {
    if (!sessionId) return undefined;
    let cancelled = false;

    // 1. Initial replay so we have the conversation history on mount.
    api.get(`/sessions/${sessionId}/events`, {
      baseURL: api.defaults.baseURL?.replace(/\/v1\/?$/, '/v2') || '/api/v2',
      headers: { Accept: 'application/json' },
      params: { since: 0, limit: 200 },
    })
      .then((res) => {
        if (cancelled) return;
        const events = res.data?.events || [];
        const messages = events
          .filter((e) => e.type === 'chat_message')
          .map(mapMessage);
        dispatch({ type: 'replace', messages, events });
      })
      .catch(() => { /* network blip — SSE will reconcile */ });

    // 2. Live tail via SSE.
    const url = `${api.defaults.baseURL?.replace(/\/v1\/?$/, '/v2') || '/api/v2'}/sessions/${sessionId}/events`;
    const source = new EventSource(url, { withCredentials: true });
    source.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data);
        dispatch({ type: 'append', event: evt });
      } catch {
        // Ignore malformed payloads (e.g. heartbeats).
      }
    };
    source.onerror = () => {
      // EventSource auto-reconnects; nothing to do here unless we want
      // to surface a status indicator (deferred to tier 2+ UX).
    };

    return () => {
      cancelled = true;
      source.close();
    };
  }, [sessionId]);

  return state;
}

export default useSessionEvents;
