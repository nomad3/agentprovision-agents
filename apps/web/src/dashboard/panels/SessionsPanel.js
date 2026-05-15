/*
 * SessionsPanel — sidebar list of chat sessions.
 *
 * Phase 1: read-only list, click a row to open it as a chat tab in the
 * editor. "+ New" navigates to /chat (legacy create flow) for now — the
 * inline create modal will land alongside the ChatTab in Phase 2.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { tabIdFor } from '../hooks/useTabs';
import chatService from '../../services/chat';

const SessionsPanel = ({ tabsApi }) => {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await chatService.listSessions();
        if (!cancelled) setSessions(resp.data || []);
      } catch (e) {
        if (!cancelled) setError(e.response?.data?.detail || 'Failed to load sessions');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleOpen = (session) => {
    tabsApi.openTab({
      id: tabIdFor('chat', session.id),
      kind: 'chat',
      sessionId: session.id,
      title: session.title || 'Untitled chat',
    });
  };

  return (
    <>
      <div className="ap-sidebar-cta">
        <button type="button" onClick={() => navigate('/chat')}>+ New session</button>
      </div>
      {loading ? (
        <div className="ap-sidebar-empty">Loading…</div>
      ) : error ? (
        <div className="ap-sidebar-empty">{error}</div>
      ) : sessions.length === 0 ? (
        <div className="ap-sidebar-empty">No sessions yet.</div>
      ) : (
        <ul className="ap-sidebar-list">
          {sessions.map((s) => {
            const tabId = tabIdFor('chat', s.id);
            const isActive = tabsApi.activeId === tabId;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  className={isActive ? 'active' : ''}
                  onClick={() => handleOpen(s)}
                  title={s.title}
                >
                  {s.title || 'Untitled chat'}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
};

export default SessionsPanel;
