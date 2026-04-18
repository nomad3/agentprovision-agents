import { useState, useCallback, useEffect } from 'react';

const stripMarkdown = (text) => {
  if (!text) return '';
  return text
    .replace(/#{1,6}\s+/g, '')           // headings
    .replace(/(\*\*|__)(.*?)\1/g, '$2')  // bold
    .replace(/(\*|_)(.*?)\1/g, '$2')     // italic
    .replace(/`{1,3}[^`]*`{1,3}/g, '')   // code
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
    .replace(/^[-*+]\s+/gm, '')          // list bullets
    .replace(/^\d+\.\s+/gm, '')          // numbered list
    .replace(/>\s+/g, '')                // blockquotes
    .replace(/\n{2,}/g, '. ')            // paragraph breaks → pause
    .trim();
};

export const useSpeechSynthesis = () => {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voices, setVoices] = useState([]);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      setSupported(true);
      
      const updateVoices = () => {
        setVoices(window.speechSynthesis.getVoices());
      };

      updateVoices();
      if (window.speechSynthesis.onvoiceschanged !== undefined) {
        window.speechSynthesis.onvoiceschanged = updateVoices;
      }
    }
  }, []);

  const cancel = useCallback(() => {
    if (supported) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
  }, [supported]);

  const speak = useCallback((text, options = {}) => {
    if (!supported || !text) return;

    cancel();

    const utterance = new SpeechSynthesisUtterance(stripMarkdown(text));
    utterance.rate = options.rate || 1.05;
    utterance.pitch = options.pitch || 1.0;
    utterance.volume = options.volume || 1.0;

    if (options.voice) {
      utterance.voice = options.voice;
    } else if (voices.length > 0) {
      // Prefer a natural-sounding voice if available
      const preferred = voices.find(v => /samantha|karen|google us english|zira/i.test(v.name));
      if (preferred) utterance.voice = preferred;
    }

    utterance.onstart = () => {
      setSpeaking(true);
      if (options.onStart) options.onStart();
    };
    utterance.onend = () => {
      setSpeaking(false);
      if (options.onEnd) options.onEnd();
    };
    utterance.onerror = (event) => {
      setSpeaking(false);
      if (options.onError) options.onError(event);
    };

    window.speechSynthesis.speak(utterance);
  }, [supported, cancel, voices]);

  return {
    supported,
    speaking,
    speak,
    cancel,
    voices
  };
};

export default useSpeechSynthesis;
