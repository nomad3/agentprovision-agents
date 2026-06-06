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

export default function ControlSafetyStrip() {
  const [state, setState] = useState(FALLBACK_STATE);
  const [busy, setBusy] = useState(false);

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
  }, [refresh]);

  const label = labelForControlMode(state.mode);
  const permissionSummary = useMemo(
    () => summarizePermissions(state.permissions),
    [state.permissions],
  );
  const title = useMemo(() => {
    const gesture = state.gesture_state || 'unknown';
    const cursor = state.cursor_global ? 'global cursor on' : 'global cursor off';
    return `Desktop safety: ${label}; gestures ${gesture}; ${cursor}\n${permissionSummary.title}`;
  }, [label, permissionSummary.title, state.gesture_state, state.cursor_global]);

  return (
    <div className={`control-safety control-safety-${state.mode}`} title={title} aria-label="Desktop control safety">
      <span className="control-safety-label">{label}</span>
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
      <span className="control-safety-permissions" title={permissionSummary.title}>
        {permissionSummary.label}
      </span>
    </div>
  );
}
