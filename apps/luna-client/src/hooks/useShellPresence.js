import { useEffect, useRef, useCallback, useState } from 'react';
import { apiFetch } from '../api';
import { enrollDesktopDevice } from '../utils/desktopDeviceEnrollment';
import { getOrCreateShellId } from '../utils/shellIdentity';

const HEARTBEAT_INTERVAL = 10000; // 10s
const BASE_CAPABILITIES = {
  can_listen: true,
  can_notify: true,
  can_observe: true,
  can_stop: true,
  can_capture_screen: false,
  can_capture_audio: false,
  can_connect_ble: false,
  can_run_local_actions: false,
  can_control_pointer: false,
  can_control_keyboard: false,
};

async function controlAwareCapabilities() {
  const capabilities = { ...BASE_CAPABILITIES };
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const state = await invoke('control_get_safety_state');
    capabilities.can_observe = Boolean(state?.can_observe);
    capabilities.can_control_pointer = Boolean(state?.can_control_pointer);
    capabilities.can_control_keyboard = Boolean(state?.can_control_keyboard);
  } catch {
    // Browser/PWA/test fallback uses conservative defaults.
  }
  return capabilities;
}

export function useShellPresence() {
  const registered = useRef(false);
  const intervalRef = useRef(null);
  const [shellId, setShellId] = useState(null);
  const [handoff, setHandoff] = useState(false);

  const register = useCallback(async () => {
    if (!shellId) return;
    try {
      const capabilities = await controlAwareCapabilities();
      const device = await enrollDesktopDevice(shellId, capabilities);
      const res = await apiFetch('/api/v1/presence/shell/register', {
        method: 'POST',
        headers: { 'X-Device-Token': device.device_token },
        body: JSON.stringify({
          shell: shellId,
          capabilities,
          device_id: device.device_id,
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
    const handleSafetyChange = () => register();
    let unlistenControlSafety;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenControlSafety = await listen('control-safety-changed', handleSafetyChange);
      } catch {
        // Browser/PWA/test fallback only uses the DOM event bridge.
      }
    })();
    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('luna:control-safety-changed', handleSafetyChange);

    return () => {
      clearInterval(intervalRef.current);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('luna:control-safety-changed', handleSafetyChange);
      unlistenControlSafety?.();
      deregister();
    };
  }, [shellId, register, deregister, heartbeat]);

  return { register, deregister, handoff, shellId };
}
