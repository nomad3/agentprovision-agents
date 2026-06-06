import { useEffect } from 'react';
import { apiFetch } from '../api';

function safeAuditBody(event, sessionId, shellId) {
  const payload = event?.payload || {};
  if (!sessionId || !shellId) return null;

  return {
    session_id: sessionId,
    shell_id: shellId,
    event_id: payload.event_id,
    event_type: payload.event_type,
    source: payload.source,
    action: payload.action,
    capability: payload.capability,
    outcome: payload.outcome,
    reason: payload.reason ?? null,
    mode: payload.mode,
    created_at_ms: payload.created_at_ms ?? null,
    screen_recording_status: payload.screen_recording_status ?? null,
    accessibility_status: payload.accessibility_status ?? null,
    automation_system_events_status: payload.automation_system_events_status ?? null,
  };
}

export function useDesktopControlAuditBridge(sessionId, shellId) {
  useEffect(() => {
    if (!sessionId || !shellId) return undefined;

    let cancelled = false;
    let unlisten;

    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        const unsubscribe = await listen('desktop-control-audit', async (event) => {
          const body = safeAuditBody(event, sessionId, shellId);
          if (!body || cancelled) return;
          try {
            await apiFetch('/api/v1/desktop-control/events/local-observation', {
              method: 'POST',
              body: JSON.stringify(body),
            });
          } catch (err) {
            console.warn('[Luna] desktop-control audit forwarding failed:', err?.message || err);
          }
        });
        if (cancelled) {
          unsubscribe?.();
        } else {
          unlisten = unsubscribe;
        }
      } catch {
        // Browser/PWA/test fallback: no native desktop-control audit channel.
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [sessionId, shellId]);
}

export { safeAuditBody };
