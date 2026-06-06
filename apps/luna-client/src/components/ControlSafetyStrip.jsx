import React, { useCallback, useEffect, useMemo, useState } from 'react';

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
    default:
      return 'Control Locked';
  }
}

async function invokeControl(command) {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke(command);
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
  return Object.entries(permissions || {}).map(([key, value]) => ({
    key,
    label: permissionLabel(key),
    status: value?.status || 'unknown',
    reason: value?.reason || '',
    requiredFor: value?.required_for || [],
  }));
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

function safeActiveAppLabel(payload) {
  const value = payload?.to_app || payload?.app_name || '';
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length > 28 ? `${trimmed.slice(0, 27)}...` : trimmed;
}

export default function ControlSafetyStrip() {
  const [state, setState] = useState(FALLBACK_STATE);
  const [busy, setBusy] = useState(false);
  const [permissionsOpen, setPermissionsOpen] = useState(false);
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

  const handleActivityPayload = useCallback((payload) => {
    const label = safeActiveAppLabel(payload);
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
    try {
      const next = await invokeControl(command);
      publishState(next);
    } catch {
      await refresh();
    } finally {
      setBusy(false);
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
  const title = useMemo(() => {
    const gesture = state.gesture_state || 'unknown';
    const cursor = state.cursor_global ? 'global cursor on' : 'global cursor off';
    return `Desktop safety: ${label}; gestures ${gesture}; ${cursor}\n${permissionSummary.title}`;
  }, [label, permissionSummary.title, state.gesture_state, state.cursor_global]);
  const alphaKernel = state.alpha_kernel || FALLBACK_STATE.alpha_kernel;
  const macosMonitor = state.macos_app_monitor || FALLBACK_STATE.macos_app_monitor;
  const alphaTitle = alphaKernel.available
    ? `Alpha CLI kernel: ${alphaKernel.binary_path || 'available'}`
    : `Alpha CLI kernel: ${alphaKernel.reason || 'missing'}`;
  const monitorTitle = [
    macosMonitor.reason || 'macOS app monitor status unavailable.',
    `AX: ${macosMonitor.accessibility_status || 'unknown'}`,
    `Events: ${macosMonitor.automation_system_events_status || 'unknown'}`,
  ].join('\n');

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
        <button
          className="control-safety-action"
          onClick={() => run('control_observe_status')}
          disabled={busy || state.mode === 'observe' || !state.can_observe}
          title="Enable observe-only mode"
        >
          Observe
        </button>
        <button
          className="control-safety-action"
          disabled={busy || !state.can_assist}
          title="Assist mode requires API governance and approval grants"
        >
          Assist
        </button>
        <button
          className="control-safety-action"
          disabled={busy || !state.can_control}
          title="Control mode is locked until command governance ships"
        >
          Control
        </button>
        <button
          className="control-safety-action"
          onClick={() => run('control_lock_all')}
          disabled={busy || state.mode === 'control_locked' || state.mode === 'stopped'}
          title="Lock observation without latching Stop"
        >
          Lock
        </button>
        <button
          className="control-safety-action control-safety-stop"
          onClick={() => run('control_stop_all')}
          disabled={busy || state.mode === 'stopped'}
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
        <div className="control-permissions" aria-label="Permission readiness details">
          {permissionDetails.length === 0 ? (
            <div className="control-permission control-permission-unknown">
              <span className="control-permission-main">
                <span className="control-permission-name">TCC</span>
                <span className="control-permission-detail">Permission readiness is unavailable.</span>
              </span>
              <span className="control-permission-status">Unknown</span>
            </div>
          ) : permissionDetails.map((permission) => (
            <div className={`control-permission control-permission-${permission.status}`} key={permission.key}>
              <span className="control-permission-main">
                <span className="control-permission-name">{permission.label}</span>
                {permission.reason && (
                  <span className="control-permission-detail">{permission.reason}</span>
                )}
                {permission.requiredFor.length > 0 && (
                  <span className="control-permission-detail">
                    Required for: {permission.requiredFor.join(', ')}
                  </span>
                )}
              </span>
              <span className="control-permission-status">{labelForPermissionStatus(permission.status)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
