import { useState, useCallback, useRef } from 'react';
import { apiStream } from '../api';

export function useLunaStream() {
  const [streaming, setStreaming] = useState(false);
  const [chunks, setChunks] = useState('');
  const abortCtrl = useRef(null);

  const cancel = useCallback(() => {
    abortCtrl.current?.abort();
  }, []);

  const send = useCallback(async (sessionId, content, { onUserSaved, onToken, onDone, onError } = {}) => {
    abortCtrl.current?.abort();
    abortCtrl.current = new AbortController();
    setStreaming(true);
    setChunks('');

    try {
      const res = await apiStream(`/api/v1/chat/sessions/${sessionId}/messages/stream`, { content }, abortCtrl.current.signal);
      if (!res.ok) throw new Error(`Stream failed: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'user_saved') onUserSaved?.(data.message);
            else if (data.type === 'token') {
              fullText += data.text;
              setChunks(fullText);
              onToken?.(data.text, fullText);
            }
            else if (data.type === 'done') onDone?.(data.message);
            else if (data.type === 'error') onError?.(data.detail);
          } catch {}
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') onError?.(err.message);
    } finally {
      setStreaming(false);
    }
  }, []);

  return { send, cancel, streaming, chunks };
}
