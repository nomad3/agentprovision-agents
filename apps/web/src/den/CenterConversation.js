import { useCallback, useEffect, useRef, useState } from 'react';

import styles from './DenShell.module.css';

/**
 * Center pane — the alpha conversation.
 *
 * Tier 0–1 scope:
 *   * Display chat_message events from the session.
 *   * Send new turns via POST (delegated to onSend callback).
 *
 * Tier 2+ will add inline tool-call cards, plan stepper, sub-agent
 * dispatch cards. Those are placed inline ABOVE the input bar by the
 * components that render them — this component owns only the message
 * list + input bar.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §3 → "Center: the conversation"
 */
export function CenterConversation({ messages, onSend, disabled, placeholder }) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);

  const submit = useCallback(async () => {
    const text = draft.trim();
    if (!text || disabled) return;
    setDraft('');
    try {
      await onSend?.(text);
    } catch {
      // Re-populate the input so the user can retry; surfacing errors
      // happens at the session level.
      setDraft(text);
    }
  }, [draft, disabled, onSend]);

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <>
      <div ref={scrollRef} className={styles.conversation} data-testid="den-conversation">
        {(messages || []).length === 0 ? (
          <div className={styles.conversationEmpty}>
            Say hi to alpha to get started.
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.event_id || m.id}
              className={
                m.role === 'user'
                  ? `${styles.message} ${styles.messageUser}`
                  : `${styles.message} ${styles.messageAlpha}`
              }
              data-role={m.role}
            >
              {m.text || m.content}
            </div>
          ))
        )}
      </div>
      <div className={styles.inputBar}>
        <textarea
          className={styles.input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder={placeholder || 'Message alpha…'}
          aria-label="Message alpha"
          disabled={disabled}
        />
        <button
          type="button"
          className={styles.sendButton}
          onClick={submit}
          disabled={disabled || !draft.trim()}
        >
          Send
        </button>
      </div>
    </>
  );
}

export default CenterConversation;
