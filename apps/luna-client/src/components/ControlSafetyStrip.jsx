import React, { useCallback, useEffect, useMemo, useState } from 'react';

const FALLBACK_STATE = {
  mode: 'control_locked',
  observe_enabled: false,
  stopped: false,
  control_locked: true,
  capture_running: false,
  gesture_state: 'unknown',
  cursor_global: false,
  can_observe: false,
  can_control_pointer: false,
  can_control_keyboard: false,
  last_stop_at_ms: null,
};

export function labelForControlMode(mode) {
  switch (mode) {
    case 'observe':
      return 'Observe';
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
  const title = useMemo(() => {
    const gesture = state.gesture_state || 'unknown';
    const cursor = state.cursor_global ? 'global cursor on' : 'global cursor off';
    return `Desktop safety: ${label}; gestures ${gesture}; ${cursor}`;
  }, [label, state.gesture_state, state.cursor_global]);

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
        className="control-safety-action control-safety-stop"
        onClick={() => run('control_stop_all')}
        disabled={busy || state.mode === 'stopped'}
        title="Stop all local desktop control and capture loops"
      >
        Stop
      </button>
    </div>
  );
}
