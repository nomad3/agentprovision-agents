/**
 * useVoice — push-to-talk recording via the browser MediaRecorder API.
 * Used by the Luna OS Podium's VoiceDispatch button: hold to record,
 * release to transcribe, transcript flows back to the caller.
 *
 * Why MediaRecorder and not the native Rust cpal pipeline:
 *   - The previous native audio commands (`start_audio_capture` /
 *     `stop_audio_capture`) shipped in PR #154 but were removed from the
 *     codebase prior to Luna OS work. Restoring them would require adding
 *     `cpal` back to the Tauri crate, signing/notarization implications,
 *     and a non-trivial amount of audio-thread code.
 *   - The Tauri 2 WebView is full WebKit — MediaRecorder is reliable on
 *     macOS, Linux WebKitGTK, and iOS WKWebView. The transcribe endpoint
 *     accepts any audio MIME, so we don't need to wrap WAV ourselves.
 *
 * If/when the native pipeline returns, this hook can swap implementations
 * without changing the Voice provider surface.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../api';

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return '';
  for (const m of MIME_CANDIDATES) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch {}
  }
  return '';
}

export function useVoice() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState(null);

  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    setError(null);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorder.addEventListener('dataavailable', (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      });
      recorder.start(250); // emit chunks every 250ms
      recorderRef.current = recorder;
      setIsRecording(true);
    } catch (e) {
      console.error('[useVoice] start failed:', e);
      setError('Microphone unavailable');
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recorderRef.current = null;
    }
  }, []);

  const stop = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder) return null;
    setIsRecording(false);

    const finalBlob = await new Promise((resolve) => {
      const handle = () => {
        const type = recorder.mimeType || 'audio/webm';
        resolve(new Blob(chunksRef.current, { type }));
      };
      recorder.addEventListener('stop', handle, { once: true });
      try { recorder.stop(); } catch { handle(); }
    });

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];

    if (!finalBlob || finalBlob.size === 0) return null;

    setTranscribing(true);
    try {
      const fd = new FormData();
      const ext = finalBlob.type.includes('mp4') ? 'm4a' : 'webm';
      fd.append('file', finalBlob, `voice-input.${ext}`);
      const token = localStorage.getItem('luna_token');
      const res = await fetch(`${API_BASE}/api/v1/media/transcribe`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      if (!res.ok) throw new Error(`Transcription failed (${res.status})`);
      const body = await res.json();
      return body.transcript || null;
    } catch (e) {
      console.error('[useVoice] transcribe failed:', e);
      setError('Transcription failed');
      return null;
    } finally {
      setTranscribing(false);
    }
  }, []);

  useEffect(() => () => {
    try { recorderRef.current?.stop(); } catch {}
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);

  return { isRecording, transcribing, error, start, stop };
}
