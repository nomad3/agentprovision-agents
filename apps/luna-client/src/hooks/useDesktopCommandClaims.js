import { useEffect, useRef } from 'react';
import { apiFetch } from '../api';
import { enrollDesktopDevice } from '../utils/desktopDeviceEnrollment';

export const DESKTOP_COMMAND_CLAIM_POLL_MS = 2000;
export const DESKTOP_COMMAND_DEFAULT_TIMEOUTS = {
  safetyTimeoutMs: 5000,
  nativeTimeoutMs: 10000,
  completeTimeoutMs: 8000,
  completeAttempts: 2,
  completeRetryDelayMs: 250,
};

const OBSERVATION_COMMANDS = {
  capture_screenshot: 'capture_screenshot',
  get_active_app: 'get_active_app',
  read_clipboard: 'read_clipboard',
};

const NATIVE_CONTROL_COMMANDS = new Set([
  'pointer_move',
  'pointer_click',
  'keyboard_type',
  'keyboard_key_chord',
]);

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

function timeoutError(label, timeoutMs) {
  return new Error(`${label} timed out after ${timeoutMs}ms`);
}

async function withTimeout(task, timeoutMs, label) {
  if (!timeoutMs || timeoutMs <= 0) return task();
  let timer;
  try {
    return await Promise.race([
      task(),
      new Promise((_, reject) => {
        timer = globalThis.setTimeout(() => reject(timeoutError(label, timeoutMs)), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) globalThis.clearTimeout(timer);
  }
}

async function apiFetchWithTimeout(path, options, timeoutMs, label) {
  if (!timeoutMs || timeoutMs <= 0 || typeof AbortController === 'undefined') {
    return withTimeout(() => apiFetch(path, options), timeoutMs, label);
  }
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      apiFetch(path, { ...options, signal: controller.signal }),
      new Promise((_, reject) => {
        timer = globalThis.setTimeout(() => {
          controller.abort();
          reject(timeoutError(label, timeoutMs));
        }, timeoutMs);
      }),
    ]);
  } catch (error) {
    if (controller.signal.aborted) throw timeoutError(label, timeoutMs);
    throw error;
  } finally {
    if (timer) globalThis.clearTimeout(timer);
  }
}

function resolveTimeouts(overrides = {}) {
  return {
    ...DESKTOP_COMMAND_DEFAULT_TIMEOUTS,
    ...overrides,
  };
}

function delay(ms) {
  if (!ms || ms <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
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

function commandEnvelopeNonce(command) {
  const nonce = command?.payload?.command_envelope?.nonce;
  return typeof nonce === 'string' && nonce.length > 0 ? nonce : null;
}

function commandCompletionMetadata(command, metadata = {}) {
  const nonce = commandEnvelopeNonce(command);
  if (!nonce) return metadata;
  return {
    ...metadata,
    envelope_nonce: nonce,
  };
}

async function completeCommand(
  command,
  shellId,
  deviceToken,
  status,
  reason = null,
  metadata = {},
  timeoutOverrides = {},
) {
  const id = commandId(command);
  if (!id) return;
  const timeouts = resolveTimeouts(timeoutOverrides);
  const attempts = Math.max(1, timeouts.completeAttempts || 1);
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await apiFetchWithTimeout(
        `/api/v1/desktop-control/commands/${id}/complete`,
        {
          method: 'POST',
          headers: { 'X-Device-Token': deviceToken },
          body: JSON.stringify({
            shell_id: shellId,
            status,
            reason,
            metadata: commandCompletionMetadata(command, metadata),
          }),
        },
        timeouts.completeTimeoutMs,
        'desktop command completion',
      );
      return;
    } catch (error) {
      lastError = error;
      if (attempt >= attempts) throw lastError;
      await delay(timeouts.completeRetryDelayMs);
    }
  }
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

async function invokeWithTimeout(invoke, command, timeoutMs) {
  return withTimeout(() => invoke(command), timeoutMs, `Tauri command ${command}`);
}

export async function executeClaimedDesktopCommand(
  command,
  shellId,
  deviceToken,
  invoke,
  timeoutOverrides = {},
) {
  const timeouts = resolveTimeouts(timeoutOverrides);
  const action = commandAction(command);
  const nativeCommand = OBSERVATION_COMMANDS[action];
  if (NATIVE_CONTROL_COMMANDS.has(action)) {
    let safety;
    try {
      safety = await invokeWithTimeout(invoke, 'control_get_safety_state', timeouts.safetyTimeoutMs);
    } catch (error) {
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'failed',
        reasonText(error) || 'desktop safety state unavailable',
        { result_kind: 'error' },
        timeouts,
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
        timeouts,
      );
      return;
    }
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'denied',
      `desktop native control disabled; ${action} denied`,
      { control_mode: safety?.mode || null, result_kind: 'unsupported' },
      timeouts,
    );
    return;
  }
  if (!nativeCommand) {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'denied',
      `unsupported desktop command action: ${action || 'unknown'}`,
      { result_kind: 'unsupported' },
      timeouts,
    );
    return;
  }

  let safety;
  try {
    safety = await invokeWithTimeout(invoke, 'control_get_safety_state', timeouts.safetyTimeoutMs);
  } catch (error) {
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'failed',
      reasonText(error) || 'desktop safety state unavailable',
      { result_kind: 'error' },
      timeouts,
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
      timeouts,
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
      timeouts,
    );
    return;
  }

  try {
    const result = await invokeWithTimeout(invoke, nativeCommand, timeouts.nativeTimeoutMs);
    const postSafety = await invokeWithTimeout(
      invoke,
      'control_get_safety_state',
      timeouts.safetyTimeoutMs,
    );
    if (postSafety?.mode === 'stopped') {
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'preempted',
        `desktop control stopped; ${action} preempted`,
        { control_mode: postSafety?.mode || null },
        timeouts,
      );
      return;
    }
    if (postSafety?.mode !== 'observe' || !postSafety?.can_observe) {
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'denied',
        `desktop observe locked; ${action} denied`,
        { control_mode: postSafety?.mode || null, can_observe: Boolean(postSafety?.can_observe) },
        timeouts,
      );
      return;
    }
    await completeCommand(
      command,
      shellId,
      deviceToken,
      'succeeded',
      null,
      safeObservationMetadata(action, result),
      timeouts,
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
      timeouts,
    );
  }
}

export function useDesktopCommandClaims(sessionId, shellId, options = {}) {
  const inFlight = useRef(false);
  const deviceTokenRef = useRef(null);
  const timeoutsRef = useRef(resolveTimeouts(options.timeouts));

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
        await invokeWithTimeout(
          invoke,
          'control_get_safety_state',
          timeoutsRef.current.safetyTimeoutMs,
        );
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
        if (claim?.status !== 'claimed' || !claim.command) return;
        if (cancelled) {
          await completeCommand(
            claim.command,
            shellId,
            deviceToken,
            'preempted',
            'desktop command cancelled before execution',
            { result_kind: 'cancelled' },
            timeoutsRef.current,
          );
          return;
        }

        try {
          await executeClaimedDesktopCommand(
            claim.command,
            shellId,
            deviceToken,
            invoke,
            timeoutsRef.current,
          );
        } catch (error) {
          await completeCommand(
            claim.command,
            shellId,
            deviceToken,
            'failed',
            reasonText(error) || 'desktop command execution failed after claim',
            { result_kind: 'error' },
            timeoutsRef.current,
          );
        }
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
