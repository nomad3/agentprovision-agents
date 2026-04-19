import { useState, useRef, useCallback, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { apiFetch, API_BASE } from '../api';

export function useVoice() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState(null);
  const chunksRef = useRef([]);
  const unlistenRef = useRef(null);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      chunksRef.current = [];
      
      // Listen for chunks from native side
      unlistenRef.current = await listen('audio-chunk', (event) => {
        chunksRef.current.push(event.payload);
      });

      await invoke('start_audio_capture');
      setIsRecording(true);
    } catch (err) {
      console.error('[Luna Voice] Start failed:', err);
      setError('Failed to access microphone');
    }
  }, []);

  const stopRecording = useCallback(async () => {
    try {
      setIsRecording(false);
      await invoke('stop_audio_capture');
      
      if (unlistenRef.current) {
        unlistenRef.current();
        unlistenRef.current = null;
      }

      if (chunksRef.current.length === 0) return null;

      // Process chunks into a single Blob
      setTranscribing(true);
      
      // Convert base64 chunks back to Float32Array samples
      const allSamples = [];
      for (const b64 of chunksRef.current) {
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const floatData = new Float32Array(bytes.buffer);
        allSamples.push(floatData);
      }

      // Flatten samples
      const totalLen = allSamples.reduce((acc, s) => acc + s.length, 0);
      const combined = new Float32Array(totalLen);
      let offset = 0;
      for (const s of allSamples) {
        combined.set(s, offset);
        offset += s.length;
      }

      // Create a WAV or OGG blob (simplified: send as raw PCM or wrapped)
      // For apps/api/app/api/v1/media.py, it uses soundfile which can read many formats.
      // Let's wrap it in a simple WAV header or use a library.
      // For now, let's create a Blob from the raw bytes (le_bytes from Rust).
      const rawBytes = new Uint8Array(combined.buffer);
      const blob = new Blob([rawBytes], { type: 'audio/wav' }); // soundfile will try to detect

      const formData = new FormData();
      formData.append('file', blob, 'voice-input.wav');

      const token = localStorage.getItem('luna_token');
      const res = await fetch(`${API_BASE}/api/v1/media/transcribe`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });

      if (!res.ok) throw new Error('Transcription failed');
      const data = await res.json();
      
      return data.transcript;
    } catch (err) {
      console.error('[Luna Voice] Stop/Transcribe failed:', err);
      setError('Transcription failed');
      return null;
    } finally {
      setTranscribing(false);
    }
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      if (unlistenRef.current) unlistenRef.current();
      if (isRecording) invoke('stop_audio_capture').catch(() => {});
    };
  }, [isRecording]);

  return {
    isRecording,
    transcribing,
    error,
    startRecording,
    stopRecording,
  };
}
