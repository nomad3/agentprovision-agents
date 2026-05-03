/**
 * Settings page at /settings/gestures — lists all bindings, lets the user
 * record/edit/delete/toggle them, surfaces conflict warnings, and exports
 * or resets the binding set.
 */
import React, { useState } from 'react';
import { useGestureBindings } from '../../hooks/useGestureBindings';
import { useGesture } from '../../hooks/useGesture';
import GestureBindingRow from './GestureBindingRow';
import GestureRecorder from './GestureRecorder';

export default function GestureBindingsPage() {
  const { bindings, loaded, error, detectConflict, upsert, remove, resetToDefaults } =
    useGestureBindings();
  const { wakeState, status } = useGesture();
  const [editing, setEditing] = useState(null); // null | {} (new) | binding (edit)

  if (!loaded) {
    return <div style={{ padding: 24, color: '#9ad' }}>Loading bindings…</div>;
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(bindings, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'luna-gesture-bindings.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ padding: 24, maxWidth: 880, margin: '0 auto' }}>
      <h2 style={{ color: '#cce' }}>Gesture Bindings</h2>
      <p style={{ color: '#9ad', fontSize: 13 }}>
        Engine state: <b>{status.state}</b>. Wake state: <b>{wakeState}</b>.
        {wakeState === 'sleeping' && ' Hold an open palm in front of the camera for 500 ms to wake.'}
      </p>
      {error && (
        <div style={{ color: '#f88', fontSize: 12, marginBottom: 12 }}>
          Save failed: {String(error.message || error)}
        </div>
      )}
      <div style={{ margin: '12px 0', display: 'flex', gap: 8 }}>
        <button onClick={() => setEditing({})} style={btnStyle}>+ New binding</button>
        <button onClick={resetToDefaults} style={btnStyle}>Reset to defaults</button>
        <button onClick={exportJson} style={btnStyle}>Export JSON</button>
      </div>
      <div style={{ border: '1px solid #234', borderRadius: 8, overflow: 'hidden' }}>
        {bindings.map((b) => (
          <GestureBindingRow
            key={b.id}
            binding={b}
            conflict={detectConflict(b)}
            onEdit={setEditing}
            onToggle={(bd) => upsert({ ...bd, enabled: !bd.enabled })}
            onDelete={remove}
          />
        ))}
        {bindings.length === 0 && (
          <div style={{ padding: 16, color: '#9ad', fontSize: 12 }}>
            No bindings configured.
          </div>
        )}
      </div>
      {editing !== null && (
        <GestureRecorder
          initial={editing.id ? editing : null}
          onSave={(b) => { upsert(b); setEditing(null); }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  );
}

const btnStyle = {
  background: 'transparent', border: '1px solid #345', color: '#cce',
  borderRadius: 4, padding: '6px 12px', fontSize: 12, cursor: 'pointer',
};
