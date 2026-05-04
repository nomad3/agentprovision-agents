/**
 * Push-to-talk button for the Luna OS podium. Hold to record, release to
 * transcribe. On transcribe success, fires `luna-podium-voice-text` so
 * useDispatchOnPoint can pair it with the most recent agent target.
 */
import React from 'react';
import { useVoiceContext } from '../../context/VoiceContext';

export default function VoiceDispatch() {
  const { isRecording, transcribing, start, stop } = useVoiceContext();

  const onDown = () => { if (!transcribing) start(); };
  const onUp = async () => {
    if (!isRecording) return;
    const text = await stop();
    if (text) {
      window.dispatchEvent(
        new CustomEvent('luna-podium-voice-text', { detail: { text } }),
      );
    }
  };

  return (
    <button
      onPointerDown={onDown}
      onPointerUp={onUp}
      onPointerLeave={onUp}
      onPointerCancel={onUp}
      disabled={transcribing}
      style={{
        position: 'absolute',
        bottom: 16,
        right: 16,
        width: 56,
        height: 56,
        borderRadius: 28,
        border: `2px solid ${isRecording ? '#f88' : '#4cf'}`,
        background: isRecording ? 'rgba(255,80,120,0.25)' : 'rgba(40,80,140,0.4)',
        color: isRecording ? '#fcc' : '#cce',
        fontSize: 20,
        cursor: 'pointer',
        zIndex: 12,
        boxShadow: isRecording ? '0 0 24px #f88' : '0 0 12px #4cf66',
      }}
      title={
        transcribing ? 'Transcribing…' : isRecording ? 'Release to send' : 'Hold to speak'
      }
      aria-label="push-to-talk"
    >
      {transcribing ? '…' : isRecording ? '●' : '🎤'}
    </button>
  );
}
