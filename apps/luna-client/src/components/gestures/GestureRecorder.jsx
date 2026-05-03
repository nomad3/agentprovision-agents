/**
 * Modal that captures a gesture three times in a row to derive a binding.
 * Reads live events from the gesture engine via useGesture(); when 3 samples
 * with the same pose+motion-kind+direction land in a row, the modal enables
 * the Save button. The user picks an action and scope, then commits.
 *
 * Engine must be Armed for events to arrive — copy in the modal nudges the
 * user to wake Luna first if it isn't.
 */
import React, { useEffect, useState } from 'react';
import { useGesture } from '../../hooks/useGesture';

const ACTION_KINDS = [
  'memory_recall', 'memory_record', 'memory_clear',
  'nav_chat', 'nav_hud', 'nav_command_palette', 'nav_bindings',
  'agent_next', 'agent_prev', 'agent_open',
  'workflow_run', 'workflow_pause', 'workflow_dismiss',
  'approve', 'dismiss',
  'mic_toggle', 'ptt_start', 'ptt_stop',
  'scroll_up', 'scroll_down', 'scroll_left', 'scroll_right',
  'zoom_in', 'zoom_out',
  'cursor_move', 'click',
  'mcp_tool', 'skill', 'custom',
];

const SCOPES = ['global', 'luna_only', 'hud_only', 'chat_only'];

// Mirror the API enum (apps/api/app/schemas/gesture_binding.py::Pose).
// `five` is intentionally absent — pose::classify maps that geometry to open_palm.

function sigKey(ev) {
  const m = ev.motion;
  if (!m || m.kind === 'none') return `${ev.pose}|none`;
  return `${ev.pose}|${m.kind}|${m.direction || ''}`;
}

export default function GestureRecorder({ initial, onSave, onCancel }) {
  const { wakeState, lastEvent } = useGesture();
  const [samples, setSamples] = useState([]);
  const [actionKind, setActionKind] = useState(initial?.action?.kind || 'nav_hud');
  const [scope, setScope] = useState(initial?.scope || 'global');

  useEffect(() => {
    if (!lastEvent) return;
    setSamples((s) => {
      if (s.length >= 3) return s;
      // Reset if signature differs from accumulated samples
      if (s.length > 0 && sigKey(s[0]) !== sigKey(lastEvent)) {
        return [lastEvent];
      }
      return [...s, lastEvent];
    });
  }, [lastEvent]);

  const consensus = samples.length === 3 ? {
    pose: samples[0].pose,
    motion: samples[0].motion && samples[0].motion.kind !== 'none' ? {
      kind: samples[0].motion.kind,
      direction: samples[0].motion.direction || undefined,
    } : undefined,
  } : null;

  const handleSave = () => {
    if (!consensus) return;
    const id = initial?.id || `u-${Date.now().toString(36)}`;
    onSave({
      id,
      gesture: {
        pose: consensus.pose,
        ...(consensus.motion ? { motion: consensus.motion } : {}),
      },
      action: { kind: actionKind },
      scope,
      enabled: true,
      user_recorded: true,
    });
  };

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true">
      <div style={dialogStyle}>
        <h3 style={{ marginTop: 0 }}>Record gesture</h3>
        <p style={{ color: '#9ad' }}>
          {wakeState !== 'armed'
            ? 'Wake Luna first — hold an open palm in front of the camera for half a second.'
            : `Perform the gesture three times. Captured ${samples.length}/3.`}
        </p>
        <pre style={preStyle}>
          {samples.length === 0
            ? '(waiting for first sample…)'
            : samples.map((s, i) => `${i + 1}. ${sigKey(s)}`).join('\n')}
        </pre>
        <div style={{ marginTop: 12 }}>
          <label style={labelStyle}>
            Action:
            <select value={actionKind} onChange={(e) => setActionKind(e.target.value)} style={selStyle}>
              {ACTION_KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          <label style={{ ...labelStyle, marginLeft: 12 }}>
            Scope:
            <select value={scope} onChange={(e) => setScope(e.target.value)} style={selStyle}>
              {SCOPES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
        </div>
        <div style={{ marginTop: 16, textAlign: 'right' }}>
          <button onClick={() => setSamples([])} style={btnStyle}>Restart capture</button>
          <button onClick={onCancel} style={{ ...btnStyle, marginLeft: 8 }}>Cancel</button>
          <button onClick={handleSave} disabled={!consensus}
            style={{ ...btnStyle, marginLeft: 8, opacity: consensus ? 1 : 0.5 }}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

const overlayStyle = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,10,0.85)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000,
};
const dialogStyle = {
  background: '#0a1024', padding: 24, borderRadius: 12,
  minWidth: 420, maxWidth: 560, color: '#cce',
  border: '1px solid #345',
};
const preStyle = {
  background: '#001020', padding: 10, fontSize: 12, minHeight: 80,
  borderRadius: 4, whiteSpace: 'pre-wrap',
};
const labelStyle = { fontSize: 12, color: '#9ad' };
const selStyle = { marginLeft: 6, background: '#001020', color: '#cce', border: '1px solid #345', padding: '4px 6px' };
const btnStyle = { background: 'transparent', border: '1px solid #345', color: '#cce', borderRadius: 4, padding: '6px 12px', cursor: 'pointer' };
