import { useState, useRef, useCallback, useEffect } from 'react';

export const useVoiceInput = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [supported, setSupported] = useState(true);
  const [error, setError] = useState(null);
  const [recordedBlob, setRecordedBlob] = useState(null);
  
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);

  useEffect(() => {
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setSupported(false);
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setRecordedBlob(null);
    audioChunksRef.current = [];
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      
      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg';
      const recorder = new MediaRecorder(stream, { mimeType });
      
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };
      
      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: mimeType });
        setRecordedBlob(blob);
        setIsRecording(false);
        
        // Stop all tracks to release the microphone
        if (streamRef.current) {
          streamRef.current.getTracks().forEach(track => track.stop());
          streamRef.current = null;
        }
      };
      
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Voice input error:', err);
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setError('Microphone access denied. Please allow microphone permissions in your browser settings.');
      } else {
        setError('Failed to start recording: ' + err.message);
      }
      setIsRecording(false);
    }
  }, []);

  const stop = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  return {
    isRecording,
    supported,
    error,
    start,
    stop,
    recordedBlob,
    setError
  };
};

export default useVoiceInput;
