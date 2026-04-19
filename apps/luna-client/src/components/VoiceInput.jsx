import React from 'react';
import { useVoice } from '../hooks/useVoice';

export default function VoiceInput({ onTranscript, disabled }) {
  const { isRecording, transcribing, startRecording, stopRecording } = useVoice();

  const handlePointerDown = (e) => {
    if (disabled || transcribing) return;
    startRecording();
  };

  const handlePointerUp = async (e) => {
    if (!isRecording) return;
    const transcript = await stopRecording();
    if (transcript) {
      onTranscript(transcript);
    }
  };

  return (
    <div className="voice-input-container">
      <button
        type="button"
        className={`luna-btn mic-btn ${isRecording ? 'recording' : ''} ${transcribing ? 'transcribing' : ''}`}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        disabled={disabled || transcribing}
        title="Hold to speak"
      >
        {transcribing ? '...' : isRecording ? 'Listening' : '🎤'}
      </button>
      {isRecording && <div className="recording-wave" />}
    </div>
  );
}
