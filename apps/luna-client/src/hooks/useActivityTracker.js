import { useEffect, useRef } from 'react';
import { apiFetch } from '../api';
import { sanitizeMacosAppMonitorEvent } from '../utils/macosAppMonitor';
import { getCachedShellId, getOrCreateShellId } from '../utils/shellIdentity';

export function useActivityTracker() {
  const shellId = useRef(getCachedShellId() || 'desktop-pending');

  useEffect(() => {
    let unlisten;
    getOrCreateShellId().then((id) => { shellId.current = id; });
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('activity-event', (event) => {
          const data = sanitizeMacosAppMonitorEvent(event.payload, shellId.current);
          if (!data) return;

          window.dispatchEvent(new CustomEvent('luna:activity-event', { detail: data }));
          apiFetch('/api/v1/activities/track', {
            method: 'POST',
            body: JSON.stringify(data),
          }).catch(() => {}); // best-effort
        });
      } catch {} // Not in Tauri (PWA mode)
    })();
    return () => { unlisten?.(); };
  }, []);
}
