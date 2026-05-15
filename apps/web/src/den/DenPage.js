import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import api from '../utils/api';

import DenShell from './DenShell';
import useSessionEvents from './hooks/useSessionEvents';

/**
 * /den — Alpha Control Plane entry point.
 *
 * Owns session selection (URL `?session=<id>` or last-active fallback).
 * Subscribes to /api/v2/sessions/{id}/events via useSessionEvents.
 * Renders the DenShell.
 *
 * Tier 0–1 scope: chat-only flow. Future tier specs add the right
 * panel content library, plan stepper, terminal drawer rendering.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md
 * Plan:   docs/plans/2026-05-15-alpha-control-plane-tier-0-1-plan.md §5
 */
export function DenPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const sessionId = searchParams.get('session');
  const [bootstrapError, setBootstrapError] = useState(null);

  // If no session in URL, create one and redirect.
  useEffect(() => {
    if (sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.post('/chat/sessions', { source: 'den' });
        if (cancelled) return;
        const newId = res.data?.id;
        if (newId) {
          setSearchParams({ session: newId }, { replace: true });
        }
      } catch (err) {
        if (!cancelled) {
          setBootstrapError('Could not start a session. Try refreshing.');
        }
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId, setSearchParams]);

  const { messages } = useSessionEvents(sessionId);

  const handleSend = useCallback(async (text) => {
    if (!sessionId) return;
    await api.post(`/chat/sessions/${sessionId}/messages`, { content: text });
  }, [sessionId]);

  if (bootstrapError) {
    return (
      <div style={{ padding: 32, color: '#f87171', fontFamily: 'sans-serif' }}>
        {bootstrapError}
      </div>
    );
  }

  return (
    <DenShell
      messages={messages}
      onSend={handleSend}
      disabled={!sessionId}
    />
  );
}

export default DenPage;
