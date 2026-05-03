/**
 * Settings page at /settings/gestures — lists all bindings, lets the user
 * record/edit/delete/toggle them, surfaces conflict warnings, and exports
 * or resets the binding set. Also exposes the global-cursor-mode opt-in
 * (gated on Accessibility being granted) and a "Re-run calibration" button.
 */
import React, { useEffect, useState } from 'react';
import { useGestureBindings } from '../../hooks/useGestureBindings';
import { useGesture } from '../../hooks/useGesture';
import GestureBindingRow from './GestureBindingRow';
import GestureRecorder from './GestureRecorder';

async function tauriInvoke(cmd, args) {
  try {
    const tauri = await import('@tauri-apps/api/core');
    return await tauri.invoke(cmd, args);
  } catch {
    return null;
  }
}

export default function GestureBindingsPage() {
  const { bindings, loaded, error, detectConflict, upsert, remove, resetToDefaults } =
    useGestureBindings();
  const { wakeState, status } = useGesture();
  const [editing, setEditing] = useState(null); // null | {} (new) | binding (edit)
  const [accessibilityOk, setAccessibilityOk] = useState(false);
  const [globalCursor, setGlobalCursor] = useState(false);
  const [globalCursorWarn, setGlobalCursorWarn] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ok = await tauriInvoke('gesture_check_accessibility');
      if (!cancelled) setAccessibilityOk(!!ok);
      const cur = await tauriInvoke('gesture_get_cursor_global');
      if (!cancelled) setGlobalCursor(!!cur);
    })();
    return () => { cancelled = true; };
  }, []);

  const toggleGlobalCursor = async () => {
    if (!globalCursor && !localStorage.getItem('luna_global_cursor_warned')) {
      setGlobalCursorWarn(true);
      return;
    }
    const next = !globalCursor;
    await tauriInvoke('gesture_set_cursor_global', { enabled: next });
    setGlobalCursor(next);
  };

  const confirmGlobalCursor = async () => {
    localStorage.setItem('luna_global_cursor_warned', '1');
    setGlobalCursorWarn(false);
    await tauriInvoke('gesture_set_cursor_global', { enabled: true });
    setGlobalCursor(true);
  };

  const rerunCalibration = () => {
    try { localStorage.removeItem('gesture_calibrated'); } catch {}
    window.location.reload();
  };

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
      <div style={{ margin: '12px 0', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={() => setEditing({})} style={btnStyle}>+ New binding</button>
        <button onClick={resetToDefaults} style={btnStyle}>Reset to defaults</button>
        <button onClick={exportJson} style={btnStyle}>Export JSON</button>
        <button onClick={rerunCalibration} style={btnStyle}>Re-run calibration</button>
      </div>

      <div style={{
        margin: '12px 0', padding: 12,
        background: 'rgba(20, 30, 60, 0.4)',
        border: '1px solid #234', borderRadius: 8,
      }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: accessibilityOk ? 1 : 0.55 }}>
          <input
            type="checkbox"
            checked={globalCursor}
            disabled={!accessibilityOk}
            onChange={toggleGlobalCursor}
          />
          <span>
            <b>Global cursor mode</b> — let cursor / click gestures fire even when Luna isn't the
            frontmost app.
            {!accessibilityOk && <span style={{ color: '#fa6', marginLeft: 8 }}>requires Accessibility permission</span>}
          </span>
        </label>
      </div>

      {globalCursorWarn && (
        <div style={overlayStyle} role="dialog" aria-modal="true">
          <div style={{ ...dialogStyle, maxWidth: 460 }}>
            <h3 style={{ marginTop: 0 }}>Heads up</h3>
            <p>
              With global cursor mode on, a pinch click will fire in <em>whatever app is in front of you</em> —
              not just inside Luna. If you accidentally pinch while Slack is frontmost, Slack gets the click.
            </p>
            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <button onClick={() => setGlobalCursorWarn(false)} style={btnStyle}>Cancel</button>
              <button onClick={confirmGlobalCursor} style={{ ...btnStyle, marginLeft: 8 }}>I understand, enable</button>
            </div>
          </div>
        </div>
      )}
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
const overlayStyle = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,10,0.85)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2500,
};
const dialogStyle = {
  background: '#0a1024', padding: 24, borderRadius: 12,
  minWidth: 360, color: '#cce', border: '1px solid #345',
};
