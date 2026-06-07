import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  activeAppLabelFromMonitorEvent,
  sanitizeMacosAppMonitorEvent,
} from '../utils/macosAppMonitor';

const FALLBACK_STATE = {
  mode: 'control_locked',
  observe_enabled: false,
  assist_enabled: false,
  control_enabled: false,
  stopped: false,
  control_locked: true,
  capture_running: false,
  gesture_state: 'unknown',
  cursor_global: false,
  can_observe: false,
  can_assist: false,
  can_control: false,
  can_control_pointer: false,
  can_control_keyboard: false,
  alpha_kernel: {
    status: 'missing',
    available: false,
    binary_path: null,
    source: null,
    platform_scope: 'macos',
    reason: 'Alpha CLI readiness is unavailable.',
  },
  macos_app_monitor: {
    platform: 'macos',
    status: 'locked',
    reason: 'macOS app monitoring is locked.',
    accessibility_status: 'unknown',
    automation_system_events_status: 'unknown',
    observed_at_ms: null,
  },
  permissions: null,
  last_stop_at_ms: null,
};

const PERMISSION_KEYS = [
  'screen_recording',
  'accessibility',
  'automation_system_events',
  'input_monitoring',
  'camera',
  'microphone',
];

export function labelForControlMode(mode) {
  switch (mode) {
    case 'observe':
      return 'Observe';
    case 'assist':
      return 'Assist';
    case 'control':
      return 'Control';
    case 'stopped':
      return 'Stopped';
    case 'stopping':
      return 'Stopping';
    default:
      return 'Control Locked';
  }
}

async function invokeControl(command, args) {
  const { invoke } = await import('@tauri-apps/api/core');
  return args ? invoke(command, args) : invoke(command);
}

function invokeControlWithTimeout(command, args, timeoutMs = 5000) {
  let timeoutId;
  return Promise.race([
    invokeControl(command, args),
    new Promise((_, reject) => {
      timeoutId = window.setTimeout(() => reject(new Error(`${command} timed out`)), timeoutMs);
    }),
  ]).finally(() => window.clearTimeout(timeoutId));
}

function readSafetyStateWithTimeout(timeoutMs = 1500) {
  return invokeControlWithTimeout('control_get_safety_state', undefined, timeoutMs);
}

function stoppingStateFrom(current) {
  return {
    ...current,
    mode: 'stopping',
    observe_enabled: false,
    assist_enabled: false,
    control_enabled: false,
    stopped: false,
    control_locked: true,
    capture_running: false,
    gesture_state: 'stopping',
    cursor_global: false,
    can_observe: false,
    can_assist: false,
    can_control: false,
    can_control_pointer: false,
    can_control_keyboard: false,
    macos_app_monitor: {
      ...(current.macos_app_monitor || FALLBACK_STATE.macos_app_monitor),
      status: 'locked',
      reason: 'macOS app monitoring is pending local Stop confirmation.',
    },
  };
}

function permissionLabel(key) {
  switch (key) {
    case 'screen_recording':
      return 'Screen';
    case 'accessibility':
      return 'AX';
    case 'automation_system_events':
      return 'Events';
    case 'input_monitoring':
      return 'Input';
    case 'camera':
      return 'Camera';
    case 'microphone':
      return 'Mic';
    default:
      return key;
  }
}

function permissionEntries(permissions) {
  return PERMISSION_KEYS
    .filter((key) => permissions?.[key])
    .map((key) => {
      const value = permissions[key];
      return {
        key,
        label: permissionLabel(key),
        status: value?.status || 'unknown',
        reason: value?.reason || '',
        requiredFor: value?.required_for || [],
      };
    });
}

export function permissionIdentity(permissions) {
  return permissions?.app_identity || null;
}

export function summarizePermissions(permissions) {
  const entries = permissionEntries(permissions);
  if (entries.length === 0) return { label: 'TCC --', title: 'Permission readiness unavailable' };
  const activeEntries = entries.filter((entry) => entry.status !== 'unknown');
  const ready = activeEntries.filter((entry) => entry.status === 'granted' || entry.status === 'not_required').length;
  const title = entries
    .map((entry) => `${entry.label}: ${entry.status}${entry.reason ? ` — ${entry.reason}` : ''}`)
    .join('\n');
  if (activeEntries.length === 0) return { label: 'TCC --', title };
  return { label: `TCC ${ready}/${activeEntries.length}`, title };
}

export function labelForPermissionStatus(status) {
  switch (status) {
    case 'granted':
      return 'Granted';
    case 'denied':
      return 'Denied';
    case 'not_required':
      return 'Not Required';
    default:
      return 'Unknown';
  }
}

export function canOpenPermissionSetup(permission) {
  return ['denied', 'unknown'].includes(permission?.status);
}

export function labelForPermissionSetupAction(permission) {
  if (permission?.status === 'denied') return 'Enable';
  if (permission?.status === 'unknown') return 'Open';
  return '';
}

export function labelForAlphaKernelStatus(status, available) {
  if (available || status === 'available') return 'Alpha OK';
  return 'Alpha --';
}

export function labelForMacosMonitorStatus(status) {
  switch (status) {
    case 'ready':
      return 'Mac Ready';
    case 'denied':
      return 'Mac Denied';
    case 'stopped':
      return 'Mac Stopped';
    case 'unsupported':
      return 'Mac --';
    default:
      return 'Mac Locked';
  }
}

// Plain-language "why is this needed" copy for each TCC permission card. Kept
// static and display-safe — never echoes raw screen/app content.
const PERMISSION_WHY = {
  screen_recording: 'Lets Luna read the screen for observation and screenshots.',
  accessibility:
    'Lets Luna read active-app and window state, and (later, behind approval) send synthetic input.',
  automation_system_events:
    'Lets Luna resolve the active app and window context through System Events.',
  input_monitoring:
    'Only needed to observe physical keyboard input — not required to send approved synthetic input.',
  camera: 'Optional — only used for gesture control.',
  microphone: 'Optional — only used for push-to-talk voice.',
};

export function permissionWhyNeeded(key) {
  return PERMISSION_WHY[key] || '';
}

// Camera and microphone are never gates for desktop control — they only power
// optional gesture/push-to-talk features, so a denied camera/mic must not read
// as a blocker.
export function isOptionalPermission(key) {
  return key === 'camera' || key === 'microphone';
}

// Automation → System Events being unknown or denied blocks reliable active-app
// awareness, even when the monitor otherwise reports ready.
export function activeAppMonitorBlocked(monitor) {
  const status = monitor?.automation_system_events_status;
  return status === 'unknown' || status === 'denied';
}

export default function ControlSafetyStrip() {
  const [state, setState] = useState(FALLBACK_STATE);
  const [busy, setBusy] = useState(false);
  const [permissionsOpen, setPermissionsOpen] = useState(false);
  const [permissionBusy, setPermissionBusy] = useState(null);
  const [activeApp, setActiveApp] = useState(null);

  const publishState = useCallback((next) => {
    const merged = { ...FALLBACK_STATE, ...next };
    setState(merged);
    window.dispatchEvent(new CustomEvent('luna:control-safety-changed', { detail: merged }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await invokeControl('control_get_safety_state');
      publishState(next);
    } catch {
      publishState(FALLBACK_STATE);
    }
  }, [publishState]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!permissionsOpen) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setPermissionsOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [permissionsOpen]);

  useEffect(() => {
    const handleFocus = () => refresh();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refresh]);

  const handleActivityPayload = useCallback((payload) => {
    const safePayload = sanitizeMacosAppMonitorEvent(payload, null);
    const label = activeAppLabelFromMonitorEvent(safePayload);
    if (label) setActiveApp(label);
  }, []);

  useEffect(() => {
    let unlisten;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('control-safety-changed', (event) => {
          publishState(event.payload);
        });
      } catch {}
    })();
    return () => { unlisten?.(); };
  }, [publishState]);

  useEffect(() => {
    let unlisten;
    const handleDomActivity = (event) => handleActivityPayload(event.detail);
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('activity-event', (event) => {
          handleActivityPayload(event.payload);
        });
      } catch {}
    })();
    window.addEventListener('luna:activity-event', handleDomActivity);
    return () => {
      window.removeEventListener('luna:activity-event', handleDomActivity);
      unlisten?.();
    };
  }, [handleActivityPayload]);

  const run = useCallback(async (command) => {
    setBusy(true);
    const optimisticStop = command === 'control_stop_all';
    if (optimisticStop) {
      publishState(stoppingStateFrom(state));
    }
    try {
      const next = await invokeControlWithTimeout(command, undefined, optimisticStop ? 1500 : 5000);
      publishState(next);
    } catch {
      if (optimisticStop) {
        try {
          const refreshed = await readSafetyStateWithTimeout(1500);
          publishState(
            refreshed?.mode === 'stopped' ? refreshed : stoppingStateFrom(refreshed || state),
          );
        } catch {
          publishState(stoppingStateFrom(state));
        }
      } else {
        await refresh();
      }
    } finally {
      setBusy(false);
    }
  }, [publishState, refresh, state]);

  const openPermissionSetup = useCallback(async (permission) => {
    if (!canOpenPermissionSetup(permission)) return;
    setPermissionBusy(permission.key);
    try {
      const next = await invokeControl('control_open_permission_setup', { permission: permission.key });
      publishState(next);
    } catch {
      await refresh();
    } finally {
      setPermissionBusy(null);
    }
  }, [publishState, refresh]);

  const label = labelForControlMode(state.mode);
  const permissionSummary = useMemo(
    () => summarizePermissions(state.permissions),
    [state.permissions],
  );
  const permissionDetails = useMemo(
    () => permissionEntries(state.permissions),
    [state.permissions],
  );
  const identity = useMemo(
    () => permissionIdentity(state.permissions),
    [state.permissions],
  );
  const signatureLabel = useMemo(() => {
    if (!identity) return null;
    return [
      identity.code_signature_kind,
      identity.code_signature_identifier,
      identity.code_signature_team_identifier ? `team ${identity.code_signature_team_identifier}` : null,
    ].filter(Boolean).join(' | ');
  }, [identity]);
  const title = useMemo(() => {
    const gesture = state.gesture_state || 'unknown';
    const cursor = state.cursor_global ? 'global cursor on' : 'global cursor off';
    return `Desktop safety: ${label}; gestures ${gesture}; ${cursor}\n${permissionSummary.title}`;
  }, [label, permissionSummary.title, state.gesture_state, state.cursor_global]);
  const alphaKernel = state.alpha_kernel || FALLBACK_STATE.alpha_kernel;
  const macosMonitor = state.macos_app_monitor || FALLBACK_STATE.macos_app_monitor;
  const stopping = state.mode === 'stopping';
  const alphaTitle = alphaKernel.available
    ? `Alpha CLI kernel: ${alphaKernel.binary_path || 'available'}`
    : `Alpha CLI kernel: ${alphaKernel.reason || 'missing'}`;
  const monitorTitle = [
    macosMonitor.reason || 'macOS app monitor status unavailable.',
    `AX: ${macosMonitor.accessibility_status || 'unknown'}`,
    `Events: ${macosMonitor.automation_system_events_status || 'unknown'}`,
  ].join('\n');
  const eventsBlocked = useMemo(
    () => activeAppMonitorBlocked(macosMonitor),
    [macosMonitor],
  );
  // Stale-identity cleanup hint: a required (non-optional) permission reading
  // denied/unknown while a running identity is known usually means macOS stored
  // the grant against a different or older Luna build.
  const staleHintVisible = useMemo(
    () =>
      Boolean(identity)
      && permissionDetails.some(
        (entry) =>
          (entry.status === 'denied' || entry.status === 'unknown')
          && !isOptionalPermission(entry.key),
      ),
    [identity, permissionDetails],
  );

  return (
    <div className="control-safety-wrap">
      <div className={`control-safety control-safety-${state.mode}`} title={title} aria-label="Desktop control safety">
        <span className="control-safety-label">{label}</span>
        <span
          className={`control-safety-chip control-safety-chip-${alphaKernel.status || 'missing'}`}
          title={alphaTitle}
        >
          {labelForAlphaKernelStatus(alphaKernel.status, alphaKernel.available)}
        </span>
        <span
          className={`control-safety-chip control-safety-chip-${macosMonitor.status || 'locked'}`}
          title={monitorTitle}
        >
          {labelForMacosMonitorStatus(macosMonitor.status)}
        </span>
        {activeApp && (
          <span className="control-safety-chip control-safety-chip-active" title={activeApp}>
            {activeApp}
          </span>
        )}
        {eventsBlocked && macosMonitor.status === 'ready' && (
          <span
            className="control-safety-chip control-safety-chip-caution"
            title="Automation / System Events is not granted; active-app awareness is blocked until you enable it."
          >
            Active-app blocked
          </span>
        )}
        <button
          className="control-safety-action"
          onClick={() => run('control_observe_status')}
          disabled={busy || stopping || state.mode === 'observe' || !state.can_observe}
          title="Enable observe-only mode"
        >
          Observe
        </button>
        <button
          className="control-safety-action"
          disabled={busy || stopping || !state.can_assist}
          title="Assist mode requires API governance and approval grants"
        >
          Assist
        </button>
        <button
          className="control-safety-action"
          disabled={busy || stopping || !state.can_control}
          title="Control mode is locked until command governance ships"
        >
          Control
        </button>
        <button
          className="control-safety-action"
          onClick={() => run('control_lock_all')}
          disabled={busy || stopping || state.mode === 'control_locked' || state.mode === 'stopped'}
          title="Lock observation without latching Stop"
        >
          Lock
        </button>
        <button
          className="control-safety-action control-safety-stop"
          onClick={() => run('control_stop_all')}
          disabled={busy || stopping || state.mode === 'stopped'}
          title="Stop all local desktop control and capture loops"
        >
          Stop
        </button>
        {state.mode === 'stopped' && (
          <button
            className="control-safety-action control-safety-resume"
            onClick={() => run('control_clear_stop')}
            disabled={busy}
            title="Clear the latched Stop and return to the locked (safe) state. Stop now persists across app relaunch, so this is the only way to resume."
          >
            Resume
          </button>
        )}
        <button
          className="control-safety-permissions"
          type="button"
          title={permissionSummary.title}
          aria-label={`Permission readiness ${permissionSummary.label}`}
          aria-expanded={permissionsOpen}
          onClick={() => setPermissionsOpen((open) => !open)}
        >
          {permissionSummary.label}
        </button>
      </div>
      {permissionsOpen && (
        <div
          className="control-permissions-backdrop"
          onClick={() => setPermissionsOpen(false)}
        >
          <div
            className="control-permissions"
            role="dialog"
            aria-modal="true"
            aria-label="Permission readiness details"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="control-permissions-header">
              <span className="control-permissions-title">Mac Permissions</span>
              <span className="control-permissions-summary">{permissionSummary.label}</span>
              <button
                className="control-permissions-recheck"
                type="button"
                aria-label="Recheck permission readiness"
                title="Re-read macOS permission status now"
                disabled={busy}
                onClick={() => refresh()}
              >
                Recheck
              </button>
              <button
                className="control-permissions-close"
                type="button"
                aria-label="Close permission readiness details"
                onClick={() => setPermissionsOpen(false)}
              >
                Close
              </button>
            </div>
            {identity && (
              <div className="control-permissions-identity">
                <span className="control-permissions-identity-title">Running Luna Identity</span>
                {identity.bundle_id && (
                  <span className="control-permissions-identity-line">Bundle: {identity.bundle_id}</span>
                )}
                {signatureLabel && (
                  <span className="control-permissions-identity-line">Signature: {signatureLabel}</span>
                )}
                {identity.app_bundle_path && (
                  <span className="control-permissions-identity-line">App: {identity.app_bundle_path}</span>
                )}
                {identity.permission_scope_note && (
                  <span className="control-permissions-identity-note">{identity.permission_scope_note}</span>
                )}
                {staleHintVisible && (
                  <span className="control-permissions-stale-hint">
                    Showing as granted for a different or older Luna build? macOS ties each
                    grant to a signed app identity. Remove the stale entry in System Settings /
                    Privacy &amp; Security, then re-add the running identity above and Recheck.
                  </span>
                )}
              </div>
            )}
            {eventsBlocked && (
              <div className="control-permissions-blocker" role="status">
                Automation / System Events is{' '}
                {macosMonitor.automation_system_events_status || 'unknown'}. Active-app awareness
                is blocked until it is granted.
              </div>
            )}
            <div className="control-permissions-list">
              {permissionDetails.length === 0 ? (
                <div className="control-permission control-permission-unknown">
                  <span className="control-permission-main">
                    <span className="control-permission-name">TCC</span>
                    <span className="control-permission-detail">Permission readiness is unavailable.</span>
                  </span>
                  <span className="control-permission-status">Unknown</span>
                </div>
              ) : permissionDetails.map((permission) => {
                const setupAllowed = canOpenPermissionSetup(permission);
                const setupLabel = labelForPermissionSetupAction(permission);
                return (
                  <div className={`control-permission control-permission-${permission.status}`} key={permission.key}>
                    <span className="control-permission-main">
                      <span className="control-permission-name">
                        {permission.label}
                        {isOptionalPermission(permission.key) && (
                          <span className="control-permission-optional">Optional</span>
                        )}
                      </span>
                      {permissionWhyNeeded(permission.key) && (
                        <span className="control-permission-why">{permissionWhyNeeded(permission.key)}</span>
                      )}
                      {permission.reason && (
                        <span className="control-permission-detail">{permission.reason}</span>
                      )}
                      {permission.requiredFor.length > 0 && (
                        <span className="control-permission-detail">
                          Required for: {permission.requiredFor.join(', ')}
                        </span>
                      )}
                    </span>
                    <span className="control-permission-side">
                      <span
                        className={`control-permission-status control-permission-pill control-permission-pill-${permission.status}`}
                      >
                        {labelForPermissionStatus(permission.status)}
                      </span>
                      {setupAllowed && (
                        <button
                          className="control-permission-action"
                          type="button"
                          disabled={busy || permissionBusy === permission.key}
                          onClick={() => openPermissionSetup(permission)}
                          aria-label={`${setupLabel} ${permission.label} permission`}
                          title={`Open macOS settings for ${permission.label}`}
                        >
                          {permissionBusy === permission.key ? 'Opening' : setupLabel}
                        </button>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
