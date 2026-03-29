import React, { useState, useEffect, useRef } from 'react';

export default function CommandPalette({ visible, onClose, onSend }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    if (visible) {
      setQuery('');
      setResult(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [visible]);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    if (visible) {
      window.addEventListener('keydown', handleKey);
      return () => window.removeEventListener('keydown', handleKey);
    }
  }, [visible, onClose]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!query.trim() || loading) return;
    setLoading(true);
    setResult(null);

    // Get active app context
    let appContext = '';
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const app = await invoke('get_active_app');
      if (app.app) appContext = `[User is in ${app.app}${app.title ? ': ' + app.title : ''}] `;
    } catch {}

    // Quick command — send to Luna via active session and show result inline
    if (onSend) {
      onSend(appContext + query.trim());
      setQuery('');
      setLoading(false);
      onClose();
    } else {
      setLoading(false);
    }
  };

  if (!visible) return null;

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette-container" onClick={e => e.stopPropagation()}>
        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            className="palette-input"
            placeholder="Ask Luna anything..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoFocus
          />
        </form>
        {loading && <div className="palette-status">Thinking...</div>}
        {result && <div className="palette-result">{result}</div>}
        <div className="palette-hint">Enter to send &middot; Esc to close</div>
      </div>
    </div>
  );
}
