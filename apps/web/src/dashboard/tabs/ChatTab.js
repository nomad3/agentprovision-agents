/*
 * ChatTab — minimal chat surface inside the IDE EditorArea.
 *
 * Phase 1 keeps scope small: load messages for the session, send a new
 * message, reactively show streamed assistant tokens. Rich features
 * (file attach, A2A panel toggle, references, agent picker) stay on
 * the legacy /chat page and surface here in Phase 2.
 */
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import chatService from '../../services/chat';
import PlanStepper from '../PlanStepper';
import InlineCliPicker from '../InlineCliPicker';
import './ChatTab.css';

const ChatTab = ({ tab }) => {
  const sessionId = tab.sessionId;
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState('');
  const threadRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMessages([]);
    (async () => {
      try {
        const resp = await chatService.listMessages(sessionId);
        if (!cancelled) setMessages(resp.data || []);
      } catch (e) {
        if (!cancelled) setError(e.response?.data?.detail || 'Failed to load messages');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [messages, streaming]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setStreaming('');
    const optimistic = { role: 'user', content: text, _optimistic: true, id: `optim-${Date.now()}` };
    setMessages((prev) => [...prev, optimistic]);
    setInput('');

    try {
      let tokens = '';
      await new Promise((resolve, reject) => {
        chatService.postMessageStream(
          sessionId,
          text,
          (tok) => { tokens += tok; setStreaming(tokens); },
          (savedUserMsg) => {
            setMessages((prev) => prev.map((m) => m.id === optimistic.id ? savedUserMsg : m));
          },
          (final) => {
            setMessages((prev) => [...prev, final]);
            setStreaming('');
            resolve();
          },
          (err) => reject(err),
        );
      });
    } catch (e) {
      setError(e?.message || 'Send failed — try again');
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
    } finally {
      setSending(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="ap-chattab">
      <div className="ap-chattab-bar">
        <span className="ap-chattab-bar-title">{tab.title}</span>
        <InlineCliPicker />
      </div>
      <PlanStepper sessionId={sessionId} />
      <div className="ap-chattab-thread" ref={threadRef}>
        {loading ? (
          <div className="ap-chattab-empty">Loading messages…</div>
        ) : error ? (
          <div className="ap-chattab-error">{error}</div>
        ) : messages.length === 0 ? (
          <div className="ap-chattab-empty">No messages yet. Say hi.</div>
        ) : (
          messages.map((m, idx) => (
            <div key={m.id || idx} className={`ap-chattab-msg ${m.role}`}>
              <div className="ap-chattab-msg-role">{m.role}</div>
              <div className="ap-chattab-msg-content ap-chattab-markdown">
                {/* Render assistant/system replies through react-markdown
                    so pipe-tables, code-fences, bold/italic, headings
                    etc. surface as real HTML instead of raw `**foo**`
                    text. User messages render via markdown too — round-
                    trips fine for plain text and lets users paste
                    formatted snippets if they choose. Defaults only,
                    no rehype-raw — keeps the XSS surface narrow. */}
                <ReactMarkdown>{m.content || ''}</ReactMarkdown>
              </div>
            </div>
          ))
        )}
        {streaming && (
          <div className="ap-chattab-msg assistant">
            <div className="ap-chattab-msg-role">assistant</div>
            <div className="ap-chattab-msg-content ap-chattab-markdown">
              <ReactMarkdown>{streaming}</ReactMarkdown>
              <span className="ap-chattab-cursor">▍</span>
            </div>
          </div>
        )}
      </div>
      <div className="ap-chattab-input">
        <textarea
          rows={2}
          placeholder="Ask alpha…  (Enter to send, Shift+Enter for newline)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={sending}
        />
        <button type="button" onClick={handleSend} disabled={sending || !input.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
};

export default ChatTab;
