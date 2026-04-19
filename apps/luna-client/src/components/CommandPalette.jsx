import React, { useState, useEffect, useRef } from 'react';
import { useVoice } from '../hooks/useVoice';

export default function CommandPalette({ visible, onClose, onSend }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const { isRecording, transcribing, startRecording, stopRecording } = useVoice();
  const inputRef = useRef(null);

  useEffect(() => {
    if (visible) {
      setQuery('');
      setResult(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [visible]);

  // Listen for voice events
  useEffect(() => {
    const handleStart = () => {
      if (visible) startRecording();
    };
    const handleStop = async () => {
      if (visible && isRecording) {
        const transcript = await stopRecording();
        if (transcript) {
          setQuery(transcript);
          // Auto-submit after voice
          handleSubmit(null, transcript);
        }
      }
    };

    window.addEventListener('luna-voice-start', handleStart);
    window.addEventListener('luna-voice-stop', handleStop);
    return () => {
      window.removeEventListener('luna-voice-start', handleStart);
      window.removeEventListener('luna-voice-stop', handleStop);
    };
  }, [visible, isRecording, startRecording, stopRecording]);

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

  const handleSubmit = async (e, overrideText) => {
    if (e) e.preventDefault();
    const text = overrideText || query;
    if (!text.trim() || loading || transcribing) return;
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
      onSend(appContext + text.trim());
      setQuery('');
      setLoading(false);
      onClose();
    } else {
      setLoading(false);
    }
  };

  if (!visible) return null;

  return (
    <div className={`palette-overlay ${isRecording ? 'recording' : ''}`} onClick={onClose}>
      <div className="palette-container" onClick={e => e.stopPropagation()}>
        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            className="palette-input"
            placeholder={isRecording ? 'Listening...' : 'Ask Luna anything...'}
            value={query}
            onChange={e => setQuery(e.target.value)}
            disabled={transcribing}
            autoFocus
          />
        </form>
        {(loading || transcribing) && (
          <div className="palette-status">
            {transcribing ? 'Transcribing audio...' : 'Thinking...'}
          </div>
        )}
        {result && <div className="palette-result">{result}</div>}
        <div className="palette-hint">
          {isRecording ? 'Release keys to send' : 'Enter to send \u00B7 Esc to close'}
        </div>
      </div>
    </div>
  );
}
