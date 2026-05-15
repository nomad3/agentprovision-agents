import { useEffect, useState } from 'react';
import { Alert, Col, Row, Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import LiveActivityFeed from '../components/dashboard/LiveActivityFeed';
import Layout from '../components/Layout';
import SubNav from '../components/SubNav';
import { alphaControlTabs, ARIA_LABEL_KEYS } from '../components/subnavConfig';
import { getDashboardStats } from '../services/analytics';
import { getOnboardingStatus } from '../services/onboarding';

const DashboardPage = () => {
  const { t } = useTranslation('dashboard');
  const { user } = useAuth();
  const navigate = useNavigate();

  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // PR-Q6: route guard. On first dashboard mount after login, probe
  // /onboarding/status. If the tenant hasn't onboarded AND hasn't
  // pressed Skip, redirect to the wizard. Failure modes (404 from
  // an older API server, transient 5xx) are swallowed silently — same
  // semantics as the CLI's `maybe_auto_trigger` helper. The wizard
  // itself also checks status on its own mount, so a server flake
  // here won't trap the user there either.
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
        // Don't bubble — onboarding probe failure shouldn't block
        // the dashboard. Mirrors the CLI's fail-soft contract.
        // eslint-disable-next-line no-console
        console.warn('onboarding-status probe failed:', e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        setLoading(true);
        const response = await getDashboardStats();
        setDashboardData(response.data);
        setError(null);
      } catch (err) {
        setError(t('error'));
        console.error('Error fetching dashboard stats:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDashboardData();
  }, []);

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-5">
          <Spinner animation="border" role="status" variant="primary" size="sm" />
          <p className="mt-3 text-muted" style={{ fontSize: 'var(--ap-fs-sm)' }}>{t('loading')}</p>
        </div>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout>
        <Alert variant="danger">{error}</Alert>
      </Layout>
    );
  }

  const { overview, activity, agents, datasets, recent_sessions } = dashboardData || {};

  // System health items — status is a semantic/categorical value, kept as enum
  const systemItems = [
    {
      label: t('system.agents'),
      value: overview?.total_agents ?? 0,
      sub: t('system.deployed', { count: overview?.total_deployments ?? 0 }),
      status: (overview?.total_deployments ?? 0) > 0 ? 'operational' : 'idle',
    },
    {
      label: t('system.integrations'),
      value: (overview?.total_data_sources ?? 0) + (overview?.total_pipelines ?? 0),
      sub: t('system.sourcesPipelines', { sources: overview?.total_data_sources ?? 0, pipelines: overview?.total_pipelines ?? 0 }),
      status: (overview?.total_data_sources ?? 0) > 0 ? 'operational' : 'idle',
    },
    {
      label: t('system.datasets'),
      value: overview?.total_datasets ?? 0,
      sub: t('system.rows', { count: (activity?.dataset_rows_total ?? 0).toLocaleString() }),
      status: (overview?.total_datasets ?? 0) > 0 ? 'operational' : 'idle',
    },
    {
      label: t('system.memory'),
      value: overview?.total_vector_stores ?? 0,
      sub: t('system.vectorStores'),
      status: (overview?.total_vector_stores ?? 0) > 0 ? 'operational' : 'idle',
    },
  ];

  // Status dot — uses semantic tokens (success vs. muted text)
  const statusDotStyle = (status) => ({
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: status === 'operational' ? 'var(--ap-success)' : 'var(--ap-text-subtle)',
    display: 'inline-block',
    marginRight: 6,
    flexShrink: 0,
  });

  const dividerStyle = (isLast) => ({
    padding: '10px 0',
    borderBottom: isLast ? 'none' : '1px solid var(--ap-border)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  });

  return (
    <Layout>
      <div style={{ maxWidth: 1100 }}>
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">{t('title')}</h1>
            <p className="ap-page-subtitle">{t('subtitle')}</p>
          </div>
        </header>

        {/* Alpha Control sub-nav: this surface absorbs AI Chat. */}
        <SubNav tabs={alphaControlTabs} ariaLabelKey={ARIA_LABEL_KEYS.alphaControl} ariaLabelFallback="Alpha Control sections" />

        {/* Tier 4 — Live activity feed at top of dashboard */}
        <LiveActivityFeed />

        {/* System Status */}
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

        {/* Quick Navigation */}
        <div className="ap-section-label">{t('quickAccess')}</div>
        <Row className="g-3 mb-4">
          {[
            { label: t('quick.aiChat'), desc: t('quick.aiChatDesc'), path: '/chat' },
            { label: t('quick.agentFleet'), desc: t('quick.agentFleetDesc'), path: '/agents' },
            { label: t('quick.integrations'), desc: t('quick.integrationsDesc'), path: '/integrations' },
            { label: t('quick.workflows'), desc: t('quick.workflowsDesc'), path: '/workflows' },
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

        {/* Two-column layout: Recent Sessions + Agent Fleet */}
        <Row className="g-3">
          <Col lg={7}>
            <div className="ap-section-label">{t('recentConversations')}</div>
            <article className="ap-card">
              <div className="ap-card-body">
                {recent_sessions && recent_sessions.length > 0 ? (
                  <div>
                    {recent_sessions.slice(0, 6).map((session, idx) => (
                      <div
                        key={session.id}
                        style={{ ...dividerStyle(idx >= Math.min(recent_sessions.length, 6) - 1), cursor: 'pointer' }}
                        onClick={() => navigate('/chat')}
                      >
                        <div>
                          <div style={{ fontSize: 'var(--ap-fs-sm)', fontWeight: 500, color: 'var(--ap-text)' }}>
                            {session.title}
                          </div>
                          <div style={{ fontSize: 'var(--ap-fs-xs)', color: 'var(--ap-text-muted)' }}>
                            {t('sessions.messages', { count: session.message_count })}
                          </div>
                        </div>
                        <div style={{ fontSize: 'var(--ap-fs-xs)', color: 'var(--ap-text-muted)', whiteSpace: 'nowrap' }}>
                          {new Date(session.created_at).toLocaleDateString()}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-center" style={{ color: 'var(--ap-text-muted)', fontSize: 'var(--ap-fs-sm)', margin: '20px 0' }}>
                    {t('sessions.noRecent')}
                  </p>
                )}
              </div>
            </article>
          </Col>

          <Col lg={5}>
            <div className="ap-section-label">{t('agentFleet')}</div>
            <article className="ap-card">
              <div className="ap-card-body">
                {agents && agents.length > 0 ? (
                  <div>
                    {agents.slice(0, 6).map((agent, idx) => (
                      <div
                        key={agent.name}
                        style={dividerStyle(idx >= Math.min(agents.length, 6) - 1)}
                      >
                        <div style={{ fontSize: 'var(--ap-fs-sm)', fontWeight: 500, color: 'var(--ap-text)' }}>
                          {agent.name}
                        </div>
                        <div className="d-flex align-items-center" style={{ gap: 4 }}>
                          <span style={statusDotStyle(agent.deployment_count > 0 ? 'operational' : 'idle')} />
                          <span style={{ fontSize: 'var(--ap-fs-xs)', color: 'var(--ap-text-muted)' }}>
                            {agent.deployment_count > 0 ? t('agents.active') : t('agents.ready')}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-center" style={{ color: 'var(--ap-text-muted)', fontSize: 'var(--ap-fs-sm)', margin: '20px 0' }}>
                    {t('agents.noAgents')}
                  </p>
                )}
              </div>
            </article>

            {/* Datasets summary */}
            <div className="ap-section-label" style={{ marginTop: 'var(--ap-space-4)' }}>{t('datasets')}</div>
            <article className="ap-card">
              <div className="ap-card-body">
                {datasets && datasets.length > 0 ? (
                  <div>
                    {datasets.slice(0, 4).map((dataset, idx) => (
                      <div
                        key={dataset.id}
                        style={{
                          padding: '8px 0',
                          borderBottom: idx < Math.min(datasets.length, 4) - 1 ? '1px solid var(--ap-border)' : 'none',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <div style={{ fontSize: 'var(--ap-fs-sm)', color: 'var(--ap-text)' }}>
                          {dataset.name}
                        </div>
                        <div style={{ fontSize: 'var(--ap-fs-xs)', color: 'var(--ap-text-muted)' }}>
                          {t('datasetsSection.rows', { count: dataset.rows?.toLocaleString() })}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-center" style={{ color: 'var(--ap-text-muted)', fontSize: 'var(--ap-fs-sm)', margin: '16px 0' }}>
                    {t('datasetsSection.noDatasets')}
                  </p>
                )}
              </div>
            </article>
          </Col>
        </Row>
      </div>
    </Layout>
  );
};

export default DashboardPage;
