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

const DESKTOP_COMMAND_ENVELOPE_SCHEMA = 'agentprovision.desktop_command_envelope.v1';
const DESKTOP_COMMAND_OBSERVATION_ENVELOPE_POLICY_VERSION = 1;
const DESKTOP_COMMAND_NATIVE_CONTROL_ENVELOPE_POLICY_VERSION = 2;
const DESKTOP_COMMAND_ENVELOPE_HMAC_SIGNATURE_ALG = 'HMAC-SHA256';
const DESKTOP_COMMAND_ENVELOPE_ED25519_SIGNATURE_ALG = 'Ed25519';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const ACTION_CAPABILITIES = {
  capture_screenshot: 'screenshot',
  get_active_app: 'active_app',
  read_clipboard: 'clipboard_read',
  pointer_move: 'pointer_control',
  pointer_click: 'pointer_control',
  keyboard_type: 'keyboard_control',
  keyboard_key_chord: 'keyboard_control',
};

// Phase 3 pointer canary: once the boundary proof is ALLOWED, the actuation
// runs through these Tauri commands (themselves flag-gated + lease-checked +
// Stop/frontmost re-checked Rust-side). Keyboard has no actuation command yet
// (Phase 4), so a keyboard proof never actuates. The canary actuates at the
// centre of the active display — deterministic, safe, reversible; real
// targeting arrives in a later phase.
const POINTER_ACTUATION_COMMANDS = {
  pointer_move: 'control_pointer_move',
  pointer_click: 'control_pointer_click',
};
const POINTER_CANARY_POINT = { x: 0.5, y: 0.5 };

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

function parseEnvelopeExpiryMs(envelope) {
  if (Number.isFinite(envelope?.expires_at_ms)) return Number(envelope.expires_at_ms);
  if (typeof envelope?.expires_at === 'string' && envelope.expires_at) {
    const parsed = Date.parse(envelope.expires_at);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function envelopeBindingFields(command, action, shellId, expectedContext = {}) {
  return {
    desktop_command_id: commandId(command),
    shell_id: shellId,
    session_id: expectedContext.sessionId || command?.session_id || null,
    device_id: command?.device_id || null,
    action,
    capability: command?.capability || ACTION_CAPABILITIES[action] || null,
    approval_id: command?.approval_id || null,
    approval_risk_tier: NATIVE_CONTROL_COMMANDS.has(action) ? 'native_control' : 'observe',
  };
}

function nativeBoundaryProofRequest(
  command,
  action,
  shellId,
  expectedContext = {},
  liveFrontmostBundleId = null,
) {
  const normalizedLiveBundle = typeof liveFrontmostBundleId === 'string'
    && liveFrontmostBundleId.trim().length > 0
    ? liveFrontmostBundleId.trim()
    : null;
  return {
    ...envelopeBindingFields(command, action, shellId, expectedContext),
    target: command?.payload?.target || command?.payload?.command_envelope?.target || null,
    live_frontmost_bundle_id: normalizedLiveBundle,
    command_envelope: command?.payload?.command_envelope || null,
    approval: command?.payload?.approval || null,
  };
}

function expectedEnvelopePolicyVersion(action) {
  return NATIVE_CONTROL_COMMANDS.has(action)
    ? DESKTOP_COMMAND_NATIVE_CONTROL_ENVELOPE_POLICY_VERSION
    : DESKTOP_COMMAND_OBSERVATION_ENVELOPE_POLICY_VERSION;
}

function isSupportedEnvelopeSignatureAlg(signatureAlg, action) {
  if (NATIVE_CONTROL_COMMANDS.has(action)) {
    return signatureAlg === DESKTOP_COMMAND_ENVELOPE_ED25519_SIGNATURE_ALG;
  }
  return (
    signatureAlg === DESKTOP_COMMAND_ENVELOPE_HMAC_SIGNATURE_ALG
    || signatureAlg === DESKTOP_COMMAND_ENVELOPE_ED25519_SIGNATURE_ALG
  );
}

function nativeBoundaryCompletion(action, proof, fallbackMode = null) {
  const reason = proof?.allowed
    ? `desktop native control disabled; ${action} denied`
    : (proof?.reason || `desktop native control disabled; ${action} denied`);
  return {
    status: reason.toLowerCase().includes('stopped') ? 'preempted' : 'denied',
    reason,
    metadata: {
      control_mode: proof?.mode || fallbackMode || null,
      native_boundary_audit_event_id: proof?.audit_event_id || null,
      native_boundary_capability: proof?.capability || ACTION_CAPABILITIES[action] || null,
      result_kind: 'native_boundary_denial',
    },
  };
}

function validateClaimedCommandEnvelope(command, action, shellId, expectedContext = {}) {
  const envelope = command?.payload?.command_envelope;
  if (!envelope || typeof envelope !== 'object') {
    return {
      ok: false,
      reason: 'desktop command envelope missing',
      metadata: { result_kind: 'error' },
    };
  }

  if (typeof envelope.nonce !== 'string' || envelope.nonce.length === 0) {
    return {
      ok: false,
      reason: 'desktop command envelope nonce missing',
      metadata: { result_kind: 'error' },
    };
  }

  if (
    envelope.schema !== DESKTOP_COMMAND_ENVELOPE_SCHEMA
    || envelope.signed !== true
    || !isSupportedEnvelopeSignatureAlg(envelope.signature_alg, action)
    || envelope.policy_version !== expectedEnvelopePolicyVersion(action)
    || envelope.issuer !== 'agentprovision-api'
  ) {
    return {
      ok: false,
      reason: 'desktop command envelope binding mismatch',
      metadata: { result_kind: 'error' },
    };
  }

  if (NATIVE_CONTROL_COMMANDS.has(action)) {
    const targetBundleId = envelope?.target?.bundle_id;
    if (typeof targetBundleId !== 'string' || targetBundleId.trim().length === 0) {
      return {
        ok: false,
        reason: 'desktop command target not allowlisted',
        metadata: { result_kind: 'error' },
      };
    }
  }

  if (typeof envelope.signature !== 'string' || envelope.signature.length === 0) {
    return {
      ok: false,
      reason: 'desktop command envelope signature invalid',
      metadata: { result_kind: 'error' },
    };
  }

  const expiresAtMs = parseEnvelopeExpiryMs(envelope);
  if (!expiresAtMs || expiresAtMs <= Date.now()) {
    return {
      ok: false,
      reason: 'desktop command envelope expired',
      metadata: { result_kind: 'error' },
    };
  }

  const approval = command?.payload?.approval;
  if (!approval || typeof approval !== 'object') {
    return {
      ok: false,
      reason: 'desktop command approval grant missing',
      metadata: { result_kind: 'error' },
    };
  }
  const commandApprovalId = command?.approval_id;
  const payloadApprovalId = approval.approval_id;
  if (
    typeof commandApprovalId !== 'string'
    || !UUID_PATTERN.test(commandApprovalId)
    || typeof payloadApprovalId !== 'string'
    || !UUID_PATTERN.test(payloadApprovalId)
  ) {
    return {
      ok: false,
      reason: 'desktop command approval grant missing',
      metadata: { result_kind: 'error' },
    };
  }
  if (commandApprovalId !== payloadApprovalId) {
    return {
      ok: false,
      reason: 'desktop command approval grant binding mismatch',
      metadata: { result_kind: 'error' },
    };
  }
  const expectedRiskTier = NATIVE_CONTROL_COMMANDS.has(action) ? 'native_control' : 'observe';
  if (
    approval.risk_tier !== expectedRiskTier
    || approval.capability !== (command?.capability || ACTION_CAPABILITIES[action])
    || envelope.risk_tier !== expectedRiskTier
    || envelope.approval_risk_tier !== expectedRiskTier
  ) {
    return {
      ok: false,
      reason: 'desktop command approval grant binding mismatch',
      metadata: { result_kind: 'error' },
    };
  }

  const expected = envelopeBindingFields(command, action, shellId, expectedContext);
  const mismatched = Object.entries(expected).some(([key, value]) => (
    value !== null && value !== undefined && envelope[key] !== value
  ));
  if (mismatched) {
    return {
      ok: false,
      reason: 'desktop command envelope binding mismatch',
      metadata: { result_kind: 'error' },
    };
  }

  return { ok: true };
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

async function invokeWithArgsTimeout(invoke, command, args, timeoutMs) {
  return withTimeout(() => invoke(command, args), timeoutMs, `Tauri command ${command}`);
}

async function readLiveFrontmostBundleId(invoke, timeouts) {
  try {
    return await invokeWithTimeout(
      invoke,
      'control_get_frontmost_app_bundle_id',
      timeouts.nativeTimeoutMs,
    );
  } catch (error) {
    console.warn('[Luna] frontmost app bundle preflight failed:', reasonText(error));
    return null;
  }
}

export async function executeClaimedDesktopCommand(
  command,
  shellId,
  deviceToken,
  invoke,
  timeoutOverrides = {},
  expectedContext = {},
) {
  const timeouts = resolveTimeouts(timeoutOverrides);
  const action = commandAction(command);
  if (OBSERVATION_COMMANDS[action] || NATIVE_CONTROL_COMMANDS.has(action)) {
    const envelopeCheck = validateClaimedCommandEnvelope(command, action, shellId, expectedContext);
    if (!envelopeCheck.ok) {
      if (NATIVE_CONTROL_COMMANDS.has(action)) {
        try {
          const proof = await invokeWithArgsTimeout(
            invoke,
            'control_prove_native_command_boundary',
            { request: nativeBoundaryProofRequest(command, action, shellId, expectedContext) },
            timeouts.nativeTimeoutMs,
          );
          const completion = nativeBoundaryCompletion(action, proof);
          await completeCommand(
            command,
            shellId,
            deviceToken,
            completion.status,
            completion.reason,
            completion.metadata,
            timeouts,
          );
          return;
        } catch (error) {
          console.warn('[Luna] native boundary proof failed for malformed claim:', reasonText(error));
        }
      }
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'denied',
        envelopeCheck.reason,
        envelopeCheck.metadata,
        timeouts,
      );
      return;
    }
  }

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
    const liveFrontmostBundleId = await readLiveFrontmostBundleId(invoke, timeouts);
    let proof;
    try {
      proof = await invokeWithArgsTimeout(
        invoke,
        'control_prove_native_command_boundary',
        {
          request: nativeBoundaryProofRequest(
            command,
            action,
            shellId,
            expectedContext,
            liveFrontmostBundleId,
          ),
        },
        timeouts.nativeTimeoutMs,
      );
    } catch (error) {
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'failed',
        reasonText(error) || 'desktop native-control boundary unavailable',
        { control_mode: safety?.mode || null, result_kind: 'error' },
        timeouts,
      );
      return;
    }
    if (!proof?.allowed) {
      const completion = nativeBoundaryCompletion(action, proof, safety?.mode || null);
      await completeCommand(
        command,
        shellId,
        deviceToken,
        completion.status,
        completion.reason,
        completion.metadata,
        timeouts,
      );
      return;
    }

    // Proof allowed → actuate. Keyboard has no actuation command yet (Phase 4),
    // so it is reported denied rather than executed.
    const actuationCommand = POINTER_ACTUATION_COMMANDS[action];
    if (!actuationCommand) {
      await completeCommand(
        command,
        shellId,
        deviceToken,
        'denied',
        `desktop native control disabled; ${action} denied`,
        {
          control_mode: proof?.mode || safety?.mode || null,
          native_boundary_audit_event_id: proof?.audit_event_id || null,
          native_boundary_capability: proof?.capability || ACTION_CAPABILITIES[action] || null,
          result_kind: 'native_boundary_denial',
        },
        timeouts,
      );
      return;
    }

    try {
      await invokeWithArgsTimeout(
        invoke,
        actuationCommand,
        { x: POINTER_CANARY_POINT.x, y: POINTER_CANARY_POINT.y },
        timeouts.nativeTimeoutMs,
      );
    } catch (error) {
      // The actuation command fails closed on every gate it re-checks
      // (flag/Stop/Observe/lease/frontmost/bounds). A 'stop'/'preempt' reason is
      // a preemption; any other gate denial is a denial; everything else failed.
      const reason = reasonText(error) || `desktop ${action} actuation failed`;
      const lowered = reason.toLowerCase();
      let status = 'failed';
      if (lowered.includes('stop') || lowered.includes('preempt')) {
        status = 'preempted';
      } else if (
        lowered.includes('disabled') ||
        lowered.includes('drift') ||
        lowered.includes('locked') ||
        lowered.includes('rate_capped') ||
        lowered.includes('denied') ||
        lowered.includes('claim_required') ||
        lowered.includes('approval_')
      ) {
        status = 'denied';
      }
      await completeCommand(
        command,
        shellId,
        deviceToken,
        status,
        reason,
        {
          control_mode: safety?.mode || null,
          native_boundary_audit_event_id: proof?.audit_event_id || null,
          native_boundary_capability: proof?.capability || ACTION_CAPABILITIES[action] || null,
          result_kind: 'native_actuation_error',
        },
        timeouts,
      );
      return;
    }

    // Re-read safety: a Stop landing during actuation is reported as preemption.
    let postSafety = null;
    try {
      postSafety = await invokeWithTimeout(
        invoke,
        'control_get_safety_state',
        timeouts.safetyTimeoutMs,
      );
    } catch (_error) {
      postSafety = null;
    }
    const preempted = postSafety?.mode === 'stopped';
    await completeCommand(
      command,
      shellId,
      deviceToken,
      preempted ? 'preempted' : 'succeeded',
      preempted
        ? `desktop control stopped; ${action} preempted`
        : `desktop ${action} actuated`,
      {
        control_mode: postSafety?.mode || safety?.mode || null,
        native_boundary_audit_event_id: proof?.audit_event_id || null,
        native_boundary_capability: proof?.capability || ACTION_CAPABILITIES[action] || null,
        result_kind: 'native_actuation',
      },
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
            { sessionId },
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
