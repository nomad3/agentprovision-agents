/**
 * VoiceContext — single shared `useVoice` instance so multiple consumers
 * (PodiumScene's voice button, the comms-panel chat input, the gesture-
 * driven push-to-talk) share one audio-chunk listener instead of stacking
 * them. Required by `luna_client_voice_pattern.md`.
 */
import React, { createContext, useContext } from 'react';
import { useVoice } from '../hooks/useVoice';

const VoiceContext = createContext(null);

export function VoiceProvider({ children }) {
  const value = useVoice();
  return <VoiceContext.Provider value={value}>{children}</VoiceContext.Provider>;
}

export function useVoiceContext() {
  const ctx = useContext(VoiceContext);
  if (!ctx) {
    // Allow consumers outside the provider — they get a benign stub.
    return {
      isRecording: false,
      transcribing: false,
      error: null,
      start: async () => {},
      stop: async () => null,
    };
  }
  return ctx;
}
