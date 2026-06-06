import { useEffect, useRef } from 'react';
import { apiFetch } from '../api';
import { enrollDesktopDevice } from '../utils/desktopDeviceEnrollment';

export const DESKTOP_COMMAND_CLAIM_POLL_MS = 2000;

const OBSERVATION_COMMANDS = {
  capture_screenshot: 'capture_screenshot',
  get_active_app: 'get_active_app',
  read_clipboard: 'read_clipboard',
};

function commandId(command) {
  return command?.desktop_command_id || command?.id;
}

function commandAction(command) {
  return command?.payload?.action || command?.action || null;
}

function reasonText(error) {
  if (!error) return '';
  if (typeof error === 'string') return error;
  return error.message || String(error);
}

function completionStatusFromReason(reason) {
  const normalized = reason.toLowerCase();
  if (normalized.includes('stopped')) return 'preempted';
  if (
    normalized.includes('denied')
    || normalized.includes('locked')
    || normalized.includes('permission')
  ) {
    return 'denied';
  }
  return 'failed';
}

function safeObservationMetadata(action, result) {
  if (action === 'capture_screenshot') {
    return {
      result_kind: 'binary',
      result_size_bytes: typeof result === 'string' ? Math.ceil((result.length * 3) / 4) : null,
    };
  }
  if (action === 'read_clipboard') {
    return {
      result_kind: 'string',
      result_size_chars: typeof result === 'string' ? result.length : null,
    };
  }
  if (action === 'get_active_app') {
    return {
      result_kind: 'json',
      result_fields: result && typeof result === 'object' ? Object.keys(result).sort() : [],
    };
  }
  return { result_kind: 'unknown' };
}

async function completeCommand(command, shellId, deviceToken, status, reason = null, metadata = {}) {
  const id = commandId(command);
  if (!id) return;
  await apiFetch(`/api/v1/desktop-control/commands/${id}/complete`, {
    method: 'POST',
    headers: { 'X-Device-Token': deviceToken },
    body: JSON.stringify({
      shell_id: shellId,
      status,
      reason,
      metadata,
    }),
  });
}

async function stopCommands(sessionId, shellId, deviceToken, reason = 'local Stop latched') {
  if (!sessionId || !shellId || !deviceToken) return;
  await apiFetch('/api/v1/desktop-control/commands/stop', {
    method: 'POST',
    headers: { 'X-Device-Token': deviceToken },
    body: JSON.stringify({
      session_id: sessionId,
      shell_id: shellId,
      reason,
    }),
  });
}

export async function executeClaimedDesktopCommand(command, shellId, deviceToken, invoke) {
  const action = commandAction(command);
  const nativeCommand = OBSERVATION_COMMANDS[action];
  if (!nativeCommand) {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'denied',
      `unsupported desktop command action: ${action || 'unknown'}`,
      { result_kind: 'unsupported' },
    );
    return;
  }

  let safety;
  try {
    safety = await invoke('control_get_safety_state');
  } catch (error) {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'failed',
      reasonText(error) || 'desktop safety state unavailable',
      { result_kind: 'error' },
    );
    return;
  }
  if (safety?.mode === 'stopped') {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'preempted',
      `desktop control stopped; ${action} preempted`,
      { control_mode: safety?.mode || null },
    );
    return;
  }
  if (safety?.mode !== 'observe' || !safety?.can_observe) {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'denied',
      `desktop observe locked; ${action} denied`,
      { control_mode: safety?.mode || null, can_observe: Boolean(safety?.can_observe) },
    );
    return;
  }

  try {
    const result = await invoke(nativeCommand);
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'succeeded',
      null,
      safeObservationMetadata(action, result),
    );
  } catch (error) {
    const reason = reasonText(error) || `${action} failed`;
    await completeCommand(
      command,
      shellId,
      deviceToken,
      completionStatusFromReason(reason),
      reason,
      { result_kind: 'error' },
    );
  }
}

export function useDesktopCommandClaims(sessionId, shellId) {
  const inFlight = useRef(false);
  const deviceTokenRef = useRef(null);

  useEffect(() => {
    if (!sessionId || !shellId) return undefined;

    let cancelled = false;
    let interval;
    let unlistenSafety;

    const ensureDeviceToken = async () => {
      if (deviceTokenRef.current) return deviceTokenRef.current;
      const enrollment = await enrollDesktopDevice(shellId, {});
      deviceTokenRef.current = enrollment.device_token;
      return deviceTokenRef.current;
    };

    const claimOnce = async () => {
      if (cancelled || inFlight.current) return;
      inFlight.current = true;
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('control_get_safety_state');
        const deviceToken = await ensureDeviceToken();
        const response = await apiFetch('/api/v1/desktop-control/commands/claim', {
          method: 'POST',
          headers: { 'X-Device-Token': deviceToken },
          body: JSON.stringify({
            session_id: sessionId,
            shell_id: shellId,
            lease_seconds: 30,
          }),
        });
        const claim = await response.json();
        if (cancelled || claim?.status !== 'claimed' || !claim.command) return;

        await executeClaimedDesktopCommand(claim.command, shellId, deviceToken, invoke);
      } catch (error) {
        console.warn('[Luna] desktop command claim loop failed:', reasonText(error));
      } finally {
        inFlight.current = false;
      }
    };

    const preemptOnStop = async (event) => {
      const mode = event?.payload?.mode || event?.detail?.mode;
      if (mode !== 'stopped') return;
      try {
        const deviceToken = await ensureDeviceToken();
        await stopCommands(sessionId, shellId, deviceToken, 'local Stop latched');
      } catch (error) {
        console.warn('[Luna] desktop command Stop preemption failed:', reasonText(error));
      }
    };

    claimOnce();
    interval = window.setInterval(claimOnce, DESKTOP_COMMAND_CLAIM_POLL_MS);

    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenSafety = await listen('control-safety-changed', preemptOnStop);
      } catch {
        // Browser/PWA/test fallback uses the DOM safety bridge below.
      }
    })();
    window.addEventListener('luna:control-safety-changed', preemptOnStop);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('luna:control-safety-changed', preemptOnStop);
      unlistenSafety?.();
    };
  }, [sessionId, shellId]);
}
