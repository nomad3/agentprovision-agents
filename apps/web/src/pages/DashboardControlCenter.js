/*
 * Alpha Control Center — the merged Dashboard + AI Chat surface.
 *
 * Wrapped in the brand `Layout` so the global sidebar / navigation /
 * theme tokens are identical to every other page in the app. The
 * IDE-shell experiment (ActivityBar + custom title/status bars) is
 * gone — it diverged from the brand UI per user feedback.
 *
 * Layout, top to bottom:
 *   - Page header (ap-page-header)
 *   - LiveActivityFeed (existing brand widget)
 *   - System Status cards (ported from legacy dashboard)
 *   - Quick Access tiles (ported)
 *   - 3-column control row:
 *       · Sessions list (left)
 *       · Active chat thread (center) — embedded ChatTab
 *       · AgentActivityPanel (right) — live v2 SSE feed
 *
 * Alpha CLI remains the kernel: chat posts hit /api/v1/chat/sessions
 * which dispatches through `cli_session_manager`. The browser makes
 * no LLM calls directly.
 */
import { useEffect, useState } from 'react';
import { Alert, Col, Row, Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { getOnboardingStatus } from '../services/onboarding';
import chatService from '../services/chat';
import agentService from '../services/agent';
import AgentActivityPanel from '../dashboard/AgentActivityPanel';
import ChatTab from '../dashboard/tabs/ChatTab';
import TerminalCard from '../dashboard/TerminalCard';
import CommandPalette from '../dashboard/CommandPalette';
import TriggerCoalitionModal from '../dashboard/TriggerCoalitionModal';
import FileTreePanel from '../dashboard/FileTreePanel';
import FileViewer from '../dashboard/FileViewer';
import { SessionEventsProvider } from '../dashboard/SessionEventsContext';
import './DashboardControlCenter.css';

const DashboardControlCenter = () => {
  const { t } = useTranslation('dashboard');
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Sessions for the embedded chat surface.
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);

  // Agents and command-palette state for ⌘K jump.
  const [agents, setAgents] = useState([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [coalitionOpen, setCoalitionOpen] = useState(false);

  // Inline session creation — keeps the user on the dashboard. Was
  // previously navigating to /chat which felt like a page-mode change.
  const [creating, setCreating] = useState(false);
  const handleNewSession = async () => {
    if (creating) return;
    setCreating(true);
    try {
      // Default title with timestamp so the user can see at a glance
      // that this is a fresh session, not an existing one. Without a
      // title the server's default labelling collides with whatever
      // session the user typed in last, which looked like "reuse" in
      // the sidebar.
      const stamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const resp = await chatService.createSession({ title: `New session · ${stamp}` });
      setSessions((prev) => [resp.data, ...prev]);
      setActiveSession(resp.data);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('createSession failed:', e);
    } finally {
      setCreating(false);
    }
  };

  // Binary mode toggle: 'simple' hides the terminal card and the live
  // agent activity panel; 'pro' shows everything. Persisted to
  // localStorage; default is 'simple' for first-touch users.
  const [mode, setMode] = useState(() => {
    try {
      const v = localStorage.getItem('alpha.dashboard.mode');
      return v === 'pro' ? 'pro' : 'simple';
    } catch { return 'simple'; }
  });
  const toggleMode = () => {
    setMode((prev) => {
      const next = prev === 'simple' ? 'pro' : 'simple';
      try { localStorage.setItem('alpha.dashboard.mode', next); } catch { /* quota */ }
      return next;
    });
  };

  // Left-panel content toggle: 'chats' (sessions list, default) or
  // 'files' (workspace tree navigator). Persisted to localStorage so
  // the preference survives reloads. When 'files', clicking a file in
  // the tree updates `openFile` which the right column picks up to
  // render <FileViewer>.
  const [leftMode, setLeftMode] = useState(() => {
    try {
      const v = localStorage.getItem('apControl.leftMode');
      return v === 'files' ? 'files' : 'chats';
    } catch { return 'chats'; }
  });
  const [openFile, setOpenFile] = useState(null);
  const switchLeftMode = (next) => {
    if (next === leftMode) return;
    setLeftMode(next);
    try { localStorage.setItem('apControl.leftMode', next); } catch { /* quota */ }
  };

  // Onboarding redirect — keeps the same gate the legacy dashboard had.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await getOnboardingStatus();
        if (cancelled) return;
        if (!status?.onboarded && !status?.deferred) {
          navigate('/onboarding', { replace: true });
        }
      } catch (e) {
        // Soft-fail; same semantics as legacy dashboard.
        // eslint-disable-next-line no-console
        console.warn('onboarding-status probe failed:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [navigate]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await chatService.listSessions();
        if (cancelled) return;
        const list = resp.data || [];
        setSessions(list);
        // Use the functional setter so a session the user *just*
        // created via handleNewSession isn't clobbered by list[0] if
        // the initial list-fetch resolves after createSession.
        if (list.length) setActiveSession((cur) => cur ?? list[0]);
      } catch {
        // Non-fatal; the dashboard still renders the widgets.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Agents feed the command palette. Fail-soft — palette still works
  // with sessions + static nav even if the agent list 403s.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await agentService.getAll();
        if (cancelled) return;
        setAgents(Array.isArray(resp.data) ? resp.data : resp.data?.agents || []);
      } catch { /* fail-soft */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // ⌘K / Ctrl+K opens the command palette. Esc handled inside the
  // palette modal itself. Ignore the shortcut if the user is editing
  // inside an input/textarea/contenteditable that's not the palette.
  useEffect(() => {
    const onKey = (e) => {
      const isPaletteShortcut = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      if (!isPaletteShortcut) return;
      e.preventDefault();
      setPaletteOpen((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-5">
          <Spinner animation="border" variant="primary" />
        </div>
      </Layout>
    );
  }

  // Keys live under `system.*` and `system.deployed/sourcesPipelines/rows/vectorStores`
  // in apps/web/src/i18n/locales/{en,es}/dashboard.json. Earlier draft used
  // `cards.*` which doesn't exist in that namespace.
  return (
    <Layout>
      <div className="dcc-container">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">{t('title')}</h1>
            <p className="ap-page-subtitle">{t('subtitle')}</p>
          </div>
          <div className="ap-page-actions">
            <button
              type="button"
              className="dcc-palette-trigger"
              onClick={() => setPaletteOpen(true)}
              title="Search and jump (⌘K)"
              aria-label="Open command palette"
            >
              <span>Search</span>
              <kbd className="dcc-palette-kbd">⌘K</kbd>
            </button>
            <button
              type="button"
              className="dcc-mode-toggle"
              onClick={toggleMode}
              aria-pressed={mode === 'pro'}
              title={mode === 'simple' ? 'Switch to Pro mode (terminal + advanced)' : 'Switch to Simple mode'}
            >
              <span className={`dcc-mode-pill ${mode === 'simple' ? 'active' : ''}`}>Simple</span>
              <span className={`dcc-mode-pill ${mode === 'pro' ? 'active' : ''}`}>Pro</span>
            </button>
          </div>
        </header>

        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          sessions={sessions}
          agents={agents}
          onSelectSession={(s) => setActiveSession(s)}
        />

        <TriggerCoalitionModal
          open={coalitionOpen}
          onClose={() => setCoalitionOpen(false)}
          sessionId={activeSession?.id || null}
        />

        {error && (
          <Alert variant="warning" dismissible onClose={() => setError(null)} className="mb-3" style={{ fontSize: 'var(--ap-fs-sm)' }}>
            {error}
          </Alert>
        )}

        {/* Stat chips removed per user feedback — they were dead weight
            when the numbers were 0/0/0/0 and even when populated they
            didn't earn the prime real estate at the top of the dash.
            The same data is reachable from /agents, /integrations,
            /memory; the bottom Quick-tile row links there directly. */}

        {/* Merged chat surface: sessions list + active thread + live agent activity */}
        {/* SessionEventsProvider opens ONE SSE connection per active
            session and shares events/status across ChatTab's PlanStepper,
            AgentActivityPanel, and TerminalCard. Previously each
            subscribed independently → 3-4 concurrent SSE connections
            per session (browser caps at 6 per origin). */}
        <SessionEventsProvider sessionId={activeSession?.id || null}>
        <div className="ap-section-label">{t('chat.title', 'Chat with Alpha')}</div>
        <Row className="g-3 dcc-chat-row">
          <Col lg={3} md={4}>
            <article className="ap-card h-100">
              <div className="ap-card-body dcc-sessions">
                {/* Chats / Files mode toggle — swaps the body of this
                    card without changing layout. localStorage-backed
                    so the preference survives reloads. */}
                <div className="dcc-left-mode-toggle" role="tablist" aria-label="Left panel mode">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={leftMode === 'chats'}
                    className={`dcc-mode-pill${leftMode === 'chats' ? ' active' : ''}`}
                    onClick={() => switchLeftMode('chats')}
                  >
                    Chats
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={leftMode === 'files'}
                    className={`dcc-mode-pill${leftMode === 'files' ? ' active' : ''}`}
                    onClick={() => switchLeftMode('files')}
                  >
                    Files
                  </button>
                </div>

                {leftMode === 'chats' ? (
                  <>
                    <div className="d-flex justify-content-between align-items-center mb-2">
                      <strong style={{ fontSize: 'var(--ap-fs-sm)' }}>{t('chat.sessions', 'Sessions')}</strong>
                      <div className="d-flex" style={{ gap: 4 }}>
                        <button
                          type="button"
                          className="ap-btn-secondary ap-btn-sm"
                          onClick={() => setCoalitionOpen(true)}
                          disabled={!activeSession}
                          title="Dispatch an A2A coalition (Propose / Critique / Revise, Plan / Verify, …)"
                        >
                          ⚡ A2A
                        </button>
                        <button
                          type="button"
                          className="ap-btn-primary ap-btn-sm"
                          onClick={handleNewSession}
                          disabled={creating}
                        >
                          + {creating ? t('chat.creating', 'Creating…') : t('chat.new', 'New')}
                        </button>
                      </div>
                    </div>
                    {sessions.length === 0 ? (
                      <p className="text-muted mb-0" style={{ fontSize: 'var(--ap-fs-sm)' }}>
                        {t('chat.empty', 'No conversations yet.')}
                      </p>
                    ) : (
                      <ul className="dcc-session-list">
                        {sessions.slice(0, 12).map((s) => (
                          <li key={s.id}>
                            <button
                              type="button"
                              className={`dcc-session-row${activeSession?.id === s.id ? ' active' : ''}`}
                              onClick={() => setActiveSession(s)}
                            >
                              <span className="dcc-session-title" title={s.title}>
                                {s.title || t('chat.untitled', 'Untitled')}
                              </span>
                              <span className="dcc-session-meta">
                                {s.message_count != null ? `${s.message_count} msgs` : ''}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <FileTreePanel onSelect={setOpenFile} />
                )}
              </div>
            </article>
          </Col>

          <Col lg={(mode === 'pro' || (leftMode === 'files' && openFile)) ? 6 : 9} md={8}>
            <article className="ap-card h-100 dcc-thread-card">
              <div className="ap-card-body dcc-thread-body">
                {activeSession ? (
                  <ChatTab tab={{ sessionId: activeSession.id, title: activeSession.title || t('chat.untitled', 'Untitled') }} />
                ) : (
                  <div className="dcc-thread-empty">
                    <p>{t('chat.pickPrompt', 'Pick a session or start a new one to chat with Alpha.')}</p>
                    <button
                      type="button"
                      className="ap-btn-primary ap-btn-sm"
                      onClick={handleNewSession}
                      disabled={creating}
                    >
                      + {creating ? t('chat.creating', 'Creating…') : t('chat.new', 'New session')}
                    </button>
                  </div>
                )}
              </div>
            </article>
          </Col>

          {/* Right column: FileViewer takes precedence over the
              AgentActivityPanel when the user is in Files mode AND has
              opened a file. Otherwise the existing pro-mode activity
              panel renders. This keeps the layout column count stable
              so the center column doesn't reflow. */}
          {leftMode === 'files' && openFile ? (
            <Col lg={3} md={12}>
              <article className="ap-card h-100 dcc-activity-card">
                <div className="ap-card-body p-0 dcc-file-viewer-body">
                  <FileViewer file={openFile} />
                </div>
              </article>
            </Col>
          ) : (mode === 'pro' && (
            <Col lg={3} md={12}>
              <article className="ap-card h-100 dcc-activity-card">
                <div className="ap-card-body p-0">
                  <AgentActivityPanel collapsed={false} sessionId={activeSession?.id || null} />
                </div>
              </article>
            </Col>
          ))}
        </Row>

        {/* Phase 2: live terminal output (collapsed by default; auto-opens
            when alpha runs a CLI subprocess in the active session). Power
            users get this; simple mode hides it. */}
        {mode === 'pro' && (
          <div className="mt-3">
            <TerminalCard sessionId={activeSession?.id || null} />
          </div>
        )}
        </SessionEventsProvider>

        {/* Compact navigation tiles at the bottom — moved here from the
            top per user feedback (less prime-real-estate noise). */}
        <div className="dcc-quick-tiles">
          {[
            { label: t('quick.agentFleet'), path: '/agents' },
            { label: t('quick.integrations'), path: '/integrations' },
            { label: t('quick.workflows'), path: '/workflows' },
            { label: t('quick.memory', 'Memory'), path: '/memory' },
          ].map((item) => (
            <button
              type="button"
              key={item.label}
              className="dcc-quick-tile"
              onClick={() => navigate(item.path)}
            >
              {item.label} →
            </button>
          ))}
        </div>
      </div>
    </Layout>
  );
};

export default DashboardControlCenter;
