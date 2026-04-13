import { useEffect, useRef } from 'react';
import { apiStream } from '../api';

/**
 * useSessionEvents
 * Subscribes to the /sessions/{id}/events SSE stream and emits Tauri events.
 * This bridges the backend Redis pub/sub to the frontend event bus.
 */
export function useSessionEvents(sessionId) {
  const abortCtrl = useRef(null);

  useEffect(() => {
    if (!sessionId) return;

    abortCtrl.current?.abort();
    abortCtrl.current = new AbortController();

    (async () => {
      try {
        const res = await apiStream(`/api/v1/chat/sessions/${sessionId}/events`, {}, abortCtrl.current.signal);
        if (!res.ok) return;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const { emit } = await import('@tauri-apps/api/event');

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const data = JSON.parse(line.slice(6));
              // Emit to all windows (SpatialHUD is in a different window)
              emit('collaboration-event', data);
            } catch (err) {
              console.warn('[useSessionEvents] Parse error:', err);
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') console.error('[useSessionEvents] Stream error:', err);
      }
    })();

    return () => abortCtrl.current?.abort();
  }, [sessionId]);
}
