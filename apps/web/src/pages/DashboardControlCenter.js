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
import LiveActivityFeed from '../components/dashboard/LiveActivityFeed';
import Layout from '../components/Layout';
import { getDashboardStats } from '../services/analytics';
import { getOnboardingStatus } from '../services/onboarding';
import chatService from '../services/chat';
import AgentActivityPanel from '../dashboard/AgentActivityPanel';
import ChatTab from '../dashboard/tabs/ChatTab';
import './DashboardControlCenter.css';

const statusDotStyle = (status) => ({
  width: 8,
  height: 8,
  borderRadius: '50%',
  background:
    status === 'ok' ? 'var(--ap-success)'
      : status === 'warning' ? 'var(--ap-warning)'
        : status === 'error' ? 'var(--ap-danger)'
          : 'var(--ap-text-muted)',
  display: 'inline-block',
});

const DashboardControlCenter = () => {
  const { t } = useTranslation('dashboard');
  const navigate = useNavigate();

  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Sessions for the embedded chat surface.
  const [sessions, setSessions] = useState([]);
  const [activeSession, setActiveSession] = useState(null);

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
        const data = await getDashboardStats();
        if (!cancelled) setDashboardData(data);
      } catch (e) {
        if (!cancelled) setError(e?.response?.data?.detail || t('errors.loadStats', 'Failed to load dashboard stats'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await chatService.listSessions();
        if (cancelled) return;
        const list = resp.data || [];
        setSessions(list);
        if (list.length && !activeSession) setActiveSession(list[0]);
      } catch {
        // Non-fatal; the dashboard still renders the widgets.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const systemItems = [
    { label: t('cards.agents'), value: dashboardData?.agents?.total ?? 0, sub: t('cards.agentsSub', { count: dashboardData?.agents?.deployed ?? 0 }), status: 'ok' },
    { label: t('cards.integrations'), value: dashboardData?.integrations?.total ?? 0, sub: t('cards.integrationsSub', { sources: dashboardData?.integrations?.data_sources ?? 0, pipelines: dashboardData?.integrations?.pipelines ?? 0 }), status: 'ok' },
    { label: t('cards.datasets'), value: dashboardData?.datasets?.total ?? 0, sub: t('cards.datasetsSub', { count: dashboardData?.datasets?.rows ?? 0 }), status: 'ok' },
    { label: t('cards.memory'), value: dashboardData?.memory?.total ?? 0, sub: t('cards.memorySub'), status: 'ok' },
  ];

  return (
    <Layout>
      <div className="dcc-container">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">{t('title')}</h1>
            <p className="ap-page-subtitle">{t('subtitle')}</p>
          </div>
        </header>

        {error && (
          <Alert variant="warning" dismissible onClose={() => setError(null)} className="mb-3" style={{ fontSize: 'var(--ap-fs-sm)' }}>
            {error}
          </Alert>
        )}

        <LiveActivityFeed />

        <div className="ap-section-label">{t('systemStatus')}</div>
        <Row className="g-3 mb-4">
          {systemItems.map((item) => (
            <Col md={3} sm={6} key={item.label}>
              <article className="ap-card h-100">
                <div className="ap-card-body">
                  <div className="d-flex align-items-center mb-2" style={{ gap: 6 }}>
                    <span style={statusDotStyle(item.status)} />
                    <span style={{ fontSize: 'var(--ap-fs-sm)', color: 'var(--ap-text-muted)', fontWeight: 500 }}>
                      {item.label}
                    </span>
                  </div>
                  <div style={{ fontSize: 'var(--ap-fs-xl)', fontWeight: 600, color: 'var(--ap-text)', lineHeight: 1.2 }}>
                    {item.value}
                  </div>
                  <div style={{ fontSize: 'var(--ap-fs-xs)', color: 'var(--ap-text-muted)', marginTop: 4 }}>
                    {item.sub}
                  </div>
                </div>
              </article>
            </Col>
          ))}
        </Row>

        <div className="ap-section-label">{t('quickAccess')}</div>
        <Row className="g-3 mb-4">
          {[
            { label: t('quick.agentFleet'), desc: t('quick.agentFleetDesc'), path: '/agents' },
            { label: t('quick.integrations'), desc: t('quick.integrationsDesc'), path: '/integrations' },
            { label: t('quick.workflows'), desc: t('quick.workflowsDesc'), path: '/workflows' },
            { label: t('quick.memory', 'Memory'), desc: t('quick.memoryDesc', 'Knowledge graph + episodes'), path: '/memory' },
          ].map((item) => (
            <Col md={3} sm={6} key={item.label}>
              <article
                className="ap-card h-100"
                role="button"
                tabIndex={0}
                onClick={() => navigate(item.path)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') navigate(item.path); }}
                style={{ cursor: 'pointer' }}
              >
                <div className="ap-card-body">
                  <div className="ap-card-title">{item.label}</div>
                  <p className="ap-card-text">{item.desc}</p>
                </div>
              </article>
            </Col>
          ))}
        </Row>

        {/* Merged chat surface: sessions list + active thread + live agent activity */}
        <div className="ap-section-label">{t('chat.title', 'Chat with Alpha')}</div>
        <Row className="g-3 dcc-chat-row">
          <Col lg={3} md={4}>
            <article className="ap-card h-100">
              <div className="ap-card-body dcc-sessions">
                <div className="d-flex justify-content-between align-items-center mb-2">
                  <strong style={{ fontSize: 'var(--ap-fs-sm)' }}>{t('chat.sessions', 'Sessions')}</strong>
                  <button type="button" className="ap-btn-primary ap-btn-sm" onClick={() => navigate('/chat')}>
                    + {t('chat.new', 'New')}
                  </button>
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
              </div>
            </article>
          </Col>

          <Col lg={6} md={8}>
            <article className="ap-card h-100 dcc-thread-card">
              <div className="ap-card-body dcc-thread-body">
                {activeSession ? (
                  <ChatTab tab={{ sessionId: activeSession.id, title: activeSession.title || t('chat.untitled', 'Untitled') }} />
                ) : (
                  <div className="dcc-thread-empty">
                    <p>{t('chat.pickPrompt', 'Pick a session or start a new one to chat with Alpha.')}</p>
                    <button type="button" className="ap-btn-primary ap-btn-sm" onClick={() => navigate('/chat')}>
                      + {t('chat.new', 'New session')}
                    </button>
                  </div>
                )}
              </div>
            </article>
          </Col>

          <Col lg={3} md={12}>
            <article className="ap-card h-100 dcc-activity-card">
              <div className="ap-card-body p-0">
                <AgentActivityPanel collapsed={false} sessionId={activeSession?.id || null} />
              </div>
            </article>
          </Col>
        </Row>
      </div>
    </Layout>
  );
};

export default DashboardControlCenter;
