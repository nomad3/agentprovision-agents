import { useEffect, useRef, useCallback, useState } from 'react';
import { apiFetch } from '../api';
import { getOrCreateShellId } from '../utils/shellIdentity';

const HEARTBEAT_INTERVAL = 10000; // 10s
const CAPABILITIES = {
  can_listen: true,
  can_notify: true,
  can_capture_screen: true,
  can_capture_audio: true,
  can_connect_ble: false,
  can_run_local_actions: true,
};

export function useShellPresence() {
  const registered = useRef(false);
  const intervalRef = useRef(null);
  const [shellId, setShellId] = useState(null);
  const [handoff, setHandoff] = useState(false);

  const register = useCallback(async () => {
    if (!shellId) return;
    try {
      const res = await apiFetch('/api/v1/presence/shell/register', {
        method: 'POST',
        body: JSON.stringify({
          shell: shellId,
          capabilities: CAPABILITIES,
        }),
      });
      registered.current = true;
      const snap = await res.json();
      if (snap.state === 'handoff') {
        setHandoff(true);
        setTimeout(() => setHandoff(false), 5000);
      }
    } catch (err) {
      console.warn('Shell register failed:', err.message);
    }
  }, [shellId]);

  const deregister = useCallback(async () => {
    if (!registered.current || !shellId) return;
    try {
      await apiFetch('/api/v1/presence/shell/deregister', {
        method: 'POST',
        body: JSON.stringify({ shell: shellId }),
      });
    } catch {
      // best-effort on teardown
    }
    registered.current = false;
  }, [shellId]);

  const heartbeat = useCallback(async () => {
    if (!registered.current) return;
    try {
      await apiFetch('/api/v1/presence/', {
        method: 'PUT',
        body: JSON.stringify({
          active_shell: shellId,
        }),
      });
    } catch {
      // silent — heartbeat is best-effort
    }
  }, [shellId]);

  useEffect(() => {
    let cancelled = false;
    getOrCreateShellId().then((id) => {
      if (!cancelled) setShellId(id);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!shellId) return undefined;
    register();
    intervalRef.current = setInterval(heartbeat, HEARTBEAT_INTERVAL);

    const handleBeforeUnload = () => deregister();
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      clearInterval(intervalRef.current);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      deregister();
    };
  }, [shellId, register, deregister, heartbeat]);

  return { register, deregister, handoff, shellId };
}
