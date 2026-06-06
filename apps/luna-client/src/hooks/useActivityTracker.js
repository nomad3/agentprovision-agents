import { useEffect, useRef } from 'react';
import { apiFetch } from '../api';
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
          const data = event.payload;
          // Post to API for server-side pattern analysis
          apiFetch('/api/v1/activities/track', {
            method: 'POST',
            body: JSON.stringify({
              ...data,
              source_shell: shellId.current,
            }),
          }).catch(() => {}); // best-effort
        });
      } catch {} // Not in Tauri (PWA mode)
    })();
    return () => { unlisten?.(); };
  }, []);
}
