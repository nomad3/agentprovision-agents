import { useCallback, useEffect, useRef } from 'react';
import { apiFetch } from '../api';
import { getCachedDesktopDeviceEnrollment } from '../utils/desktopDeviceEnrollment';

const POLL_INTERVAL_MS = 1500;
const LEASE_MS = 10000;
const OBSERVATION_COMMANDS = {
  capture_screenshot: 'capture_screenshot',
  get_active_app: 'get_active_app',
  read_clipboard: 'read_clipboard',
};

function leaseExpired(claim) {
  const expiresAt = Date.parse(claim?.lease_expires_at || '');
  return Number.isFinite(expiresAt) && Date.now() >= expiresAt;
}

async function invokeObservation(action) {
  const { invoke } = await import('@tauri-apps/api/core');
  if (!OBSERVATION_COMMANDS[action]) {
    throw new Error('unsupported desktop command action');
  }
  const state = await invoke('control_get_safety_state');
  if (state?.mode === 'stopped' || state?.stopped) {
    throw new Error('desktop control stopped');
  }
  return invoke(OBSERVATION_COMMANDS[action]);
}

async function ackCommand(shellId, deviceToken, claim, outcome, reason = null) {
  await apiFetch(`/api/v1/desktop-control/commands/${claim.command_id}/ack`, {
    method: 'POST',
    headers: { 'X-Device-Token': deviceToken },
    body: JSON.stringify({
      shell_id: shellId,
      lease_id: claim.lease_id,
      outcome,
      reason,
    }),
  });
}

export function useDesktopCommandDownchannel(shellId) {
  const busy = useRef(false);

  const poll = useCallback(async () => {
    if (!shellId || busy.current) return;
    const enrollment = getCachedDesktopDeviceEnrollment(shellId);
    if (!enrollment?.device_token) return;

    busy.current = true;
    try {
      const response = await apiFetch('/api/v1/desktop-control/commands/claim', {
        method: 'POST',
        headers: { 'X-Device-Token': enrollment.device_token },
        body: JSON.stringify({ shell_id: shellId, lease_ms: LEASE_MS }),
      });
      const claim = await response.json();
      if (claim.status !== 'claimed') return;

      if (leaseExpired(claim)) {
        await ackCommand(shellId, enrollment.device_token, claim, 'denied', 'desktop command lease expired before execution');
        return;
      }

      try {
        await ackCommand(shellId, enrollment.device_token, claim, 'running');
        if (leaseExpired(claim)) {
          await ackCommand(shellId, enrollment.device_token, claim, 'failed', 'desktop command lease expired before invocation');
          return;
        }
        await invokeObservation(claim.action);
        await ackCommand(shellId, enrollment.device_token, claim, 'succeeded');
      } catch (err) {
        await ackCommand(shellId, enrollment.device_token, claim, 'failed', err?.message || 'desktop command failed');
      }
    } catch (err) {
      console.warn('Desktop command down-channel failed:', err.message);
    } finally {
      busy.current = false;
    }
  }, [shellId]);

  useEffect(() => {
    if (!shellId) return undefined;
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    poll();
    return () => clearInterval(interval);
  }, [shellId, poll]);
}

export const __desktopCommandDownchannelTest = {
  leaseExpired,
  invokeObservation,
};
