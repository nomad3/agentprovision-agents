import { useEffect, useMemo, useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import {
  FaCheckCircle,
  FaExclamationTriangle,
  FaFolderOpen,
  FaHeartbeat,
  FaPlug,
  FaRobot,
  FaTasks,
} from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import api from '../services/api';
import { formatApiError } from '../services/apiError';
import './VetPracticeDashboardPage.css';

const statusClass = (status) => {
  if (status === 'production' || status === 'active') return 'ap-status-production';
  if (status === 'staging') return 'ap-status-staging';
  if (status === 'missing') return 'ap-status-deprecated';
  return 'ap-status-draft';
};

const readinessLabel = (flow) => {
  if (flow.ready) return 'Ready';
  if (!flow.agent_present) return 'Missing agent';
  if (flow.workflow && !flow.workflow.installed) return 'Missing workflow';
  return 'Needs file storage';
};

const VetPracticeDashboardPage = () => {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api.get('/vet-practice/dashboard', { params: { variant: 'gp_full' } })
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err, 'Failed to load veterinary practice dashboard.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const metricTiles = useMemo(() => {
    const summary = data?.summary || {};
    return [
      { label: 'Agents', value: `${summary.agents_present || 0}/${summary.agents_expected || 0}`, Icon: FaRobot },
      { label: 'File Storage', value: `${summary.storage_connected || 0}/${summary.storage_expected || 0}`, Icon: FaFolderOpen },
      { label: 'Flows Ready', value: `${summary.flows_ready || 0}/${summary.flows_expected || 0}`, Icon: FaTasks },
      { label: 'Workflows', value: `${summary.workflows_installed || 0}/${summary.workflows_expected || 0}`, Icon: FaHeartbeat },
    ];
  }, [data?.summary]);

  return (
    <Layout>
      <div className="vet-practice-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">Veterinary Practice</h1>
            <p className="ap-page-subtitle">
              {data?.practice_name || 'Practice'} · file-first MVP for Dr. Angelo and Dr. Brett workflows
            </p>
          </div>
          <div className="ap-page-actions">
            <button type="button" className="ap-btn-secondary" onClick={() => navigate('/integrations')}>
              <FaPlug size={12} /> File Storage
            </button>
            <button type="button" className="ap-btn-secondary" onClick={() => navigate('/workflows')}>
              <FaTasks size={12} /> Workflows
            </button>
            <button type="button" className="ap-btn-primary" onClick={() => navigate('/agents')}>
              <FaRobot size={12} /> Agents
            </button>
          </div>
        </header>

        {error && <Alert variant="danger" dismissible onClose={() => setError('')}>{error}</Alert>}

        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" size="sm" variant="primary" />
            <p className="mt-2 text-muted" style={{ fontSize: '0.82rem' }}>Loading practice dashboard...</p>
          </div>
        ) : data && (
          <>
            <section className="vet-practice-metrics" aria-label="Practice readiness metrics">
              {metricTiles.map(({ label, value, Icon }) => (
                <article className="ap-card vet-practice-metric" key={label}>
                  <div className="ap-card-body">
                    <Icon className="vet-practice-metric__icon" aria-hidden="true" />
                    <div>
                      <div className="vet-practice-metric__value">{value}</div>
                      <div className="vet-practice-metric__label">{label}</div>
                    </div>
                  </div>
                </article>
              ))}
            </section>

            <section className="vet-practice-section">
              <div className="ap-section-label">File Repositories</div>
              <div className="vet-practice-storage">
                {(data.storage || []).map((store) => (
                  <article className="ap-card" key={store.integration_name}>
                    <div className="ap-card-body vet-practice-storage-card">
                      <div>
                        <h3 className="ap-card-title">{store.display_name}</h3>
                        <p className="ap-card-text">
                          {store.account_email || 'Connect this repository for practice packets.'}
                        </p>
                      </div>
                      <span className={`ap-status ${store.connected ? 'ap-status-production' : 'ap-status-draft'}`}>
                        <span className="ap-status-dot" />
                        {store.connected ? 'Connected' : store.configured ? 'Configured' : 'Needed'}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="vet-practice-section">
              <div className="ap-section-label">Core File Flows</div>
              <div className="vet-practice-flow-list">
                {(data.flows || []).map((flow) => (
                  <article className="ap-card vet-practice-flow" key={flow.key}>
                    <div className="ap-card-body">
                      <div className="vet-practice-flow__head">
                        <div>
                          <h3 className="ap-card-title">{flow.name}</h3>
                          <p className="ap-card-text">{flow.description}</p>
                        </div>
                        <span className={`ap-status ${flow.ready ? 'ap-status-production' : 'ap-status-draft'}`}>
                          {flow.ready ? <FaCheckCircle size={11} /> : <FaExclamationTriangle size={11} />}
                          {readinessLabel(flow)}
                        </span>
                      </div>
                      <div className="vet-practice-flow__meta">
                        <span>{flow.primary_agent}</span>
                        <span>{flow.workflow_template}</span>
                        <span>{flow.approval_required ? 'Approval gated' : 'Staff confirmed'}</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="vet-practice-section vet-practice-two-col">
              <div>
                <div className="ap-section-label">Practice Agents</div>
                <div className="vet-practice-agent-list">
                  {(data.agents || []).map((agent) => (
                    <article className="ap-card" key={agent.name}>
                      <div className="ap-card-body vet-practice-agent-row">
                        <div>
                          <h3 className="ap-card-title">{agent.name}</h3>
                          <p className="ap-card-text">{agent.description}</p>
                        </div>
                        <span className={`ap-status ${statusClass(agent.status)}`}>
                          <span className="ap-status-dot" />
                          {agent.status}
                        </span>
                      </div>
                    </article>
                  ))}
                </div>
              </div>

              <div>
                <div className="ap-section-label">Future Practice Systems</div>
                <div className="vet-practice-future-list">
                  {(data.future_practice_systems || []).map((item) => (
                    <article className="ap-card" key={item.key}>
                      <div className="ap-card-body">
                        <h3 className="ap-card-title">{item.name}</h3>
                        <p className="ap-card-text">{item.note}</p>
                        <span className="ap-badge-outline mt-3">{item.status}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </section>
          </>
        )}
      </div>
    </Layout>
  );
};

export default VetPracticeDashboardPage;
