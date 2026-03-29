import { useEffect, useRef } from 'react';
import { apiFetch } from '../api';

export function useActivityTracker() {
  const shellId = useRef(sessionStorage.getItem('luna_shell_id') || 'desktop');

  useEffect(() => {
    let unlisten;
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
