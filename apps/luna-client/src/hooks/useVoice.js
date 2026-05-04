/**
 * useVoice — push-to-talk recording via the existing Rust `start_audio_capture`
 * and `stop_audio_capture` Tauri commands. Audio arrives in chunks via the
 * `audio-chunk` Tauri event (base64-encoded Float32 PCM); on stop, we
 * concatenate, wrap in a WAV (RIFF/PCM16) header, and POST to
 * `/api/v1/media/transcribe`. Returns the transcript text.
 *
 * Per `luna_client_voice_pattern.md`:
 *   - The Rust cpal stream stays on its spawning thread (CoreAudio-safe;
 *     handled in lib.rs already).
 *   - WAV header is required by the transcription pipeline.
 *   - This hook is consumed via VoiceProvider so a single audio-chunk
 *     listener doesn't double-up across components.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../api';

function pcmFloat32ToWav(samples, sampleRate, channels) {
  const bytesPerSample = 2;
  const blockAlign = channels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);              // PCM
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);             // bits per sample
  writeString(36, 'data');
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: 'audio/wav' });
}

export function useVoice() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState(null);

  const chunksRef = useRef([]);
  const unlistenRef = useRef(null);
  const audioConfigRef = useRef({ sampleRate: 48000, channels: 1 });
  const recordingFlagRef = useRef(false);

  useEffect(() => { recordingFlagRef.current = isRecording; }, [isRecording]);

  const start = useCallback(async () => {
    if (recordingFlagRef.current) return;
    try {
      setError(null);
      chunksRef.current = [];
      const tauriEvent = await import('@tauri-apps/api/event');
      const tauriCore = await import('@tauri-apps/api/core');
      unlistenRef.current = await tauriEvent.listen('audio-chunk', (e) => {
        chunksRef.current.push(e.payload);
      });
      const cfg = await tauriCore.invoke('start_audio_capture');
      if (cfg && typeof cfg.sample_rate === 'number') {
        audioConfigRef.current = {
          sampleRate: cfg.sample_rate,
          channels: cfg.channels || 1,
        };
      }
      recordingFlagRef.current = true;
      setIsRecording(true);
    } catch (e) {
      console.error('[useVoice] start failed:', e);
      if (unlistenRef.current) { try { unlistenRef.current(); } catch {} unlistenRef.current = null; }
      setError('Failed to access microphone');
    }
  }, []);

  const stop = useCallback(async () => {
    if (!recordingFlagRef.current) return null;
    try {
      recordingFlagRef.current = false;
      setIsRecording(false);
      const tauriCore = await import('@tauri-apps/api/core');
      await tauriCore.invoke('stop_audio_capture').catch(() => {});
      if (unlistenRef.current) { try { unlistenRef.current(); } catch {} unlistenRef.current = null; }

      if (chunksRef.current.length === 0) return null;
      setTranscribing(true);

      // chunks are base64-encoded Float32 buffers — decode and concat
      const float32Chunks = [];
      let total = 0;
      for (const b64 of chunksRef.current) {
        const bin = atob(b64);
        const u8 = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        const fl = new Float32Array(u8.buffer, u8.byteOffset, u8.byteLength / 4);
        float32Chunks.push(fl);
        total += fl.length;
      }
      const all = new Float32Array(total);
      let offset = 0;
      for (const f of float32Chunks) { all.set(f, offset); offset += f.length; }

      const { sampleRate, channels } = audioConfigRef.current;
      const wav = pcmFloat32ToWav(all, sampleRate, channels);

      const fd = new FormData();
      fd.append('file', wav, 'voice-input.wav');
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
      console.error('[useVoice] stop/transcribe failed:', e);
      setError('Transcription failed');
      return null;
    } finally {
      setTranscribing(false);
      chunksRef.current = [];
    }
  }, []);

  useEffect(() => () => {
    if (unlistenRef.current) { try { unlistenRef.current(); } catch {} unlistenRef.current = null; }
    if (recordingFlagRef.current) {
      import('@tauri-apps/api/core')
        .then((t) => t.invoke('stop_audio_capture').catch(() => {}))
        .catch(() => {});
      recordingFlagRef.current = false;
    }
  }, []);

  return { isRecording, transcribing, error, start, stop };
}
