import React, { useState, useEffect, useCallback } from 'react';
import { apiJson } from '../api';

export default function ClipboardToast() {
  const [toast, setToast] = useState(null);
  const timerRef = React.useRef(null);

  const handleClipboard = useCallback(async (text) => {
    if (!text || text.length < 3 || text.length > 200) return;

    // Search knowledge graph for the clipboard content
    try {
      const results = await apiJson(`/api/v1/knowledge/entities?search=${encodeURIComponent(text.trim().substring(0, 100))}&limit=1`);
      if (results && results.length > 0) {
        const entity = results[0];
        setToast({
          name: entity.name,
          category: entity.category,
          description: entity.description?.substring(0, 120),
        });
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setToast(null), 5000);
      }
    } catch {}
  }, []);

  useEffect(() => {
    let unlisten;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('clipboard-changed', (event) => {
          handleClipboard(event.payload);
        });
      } catch {} // Not in Tauri
    })();
    return () => { unlisten?.(); clearTimeout(timerRef.current); };
  }, [handleClipboard]);

  if (!toast) return null;

  return (
    <div className="clipboard-toast">
      <div className="clipboard-toast-header">
        <span className="clipboard-toast-category">{toast.category}</span>
        <span className="clipboard-toast-name">{toast.name}</span>
      </div>
      {toast.description && <p className="clipboard-toast-desc">{toast.description}</p>}
    </div>
  );
}
