import { useEffect, useMemo, useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import {
  FaCheckCircle,
  FaClipboardList,
  FaExclamationTriangle,
  FaFileAlt,
  FaFolderOpen,
  FaHeartbeat,
  FaMapMarkerAlt,
  FaPlayCircle,
  FaPlug,
  FaRobot,
  FaShieldAlt,
  FaTasks,
  FaUserMd,
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
  if (flow.workflow && !flow.workflow.installed) return 'Install workflow';
  return 'Connect files';
};

const titleize = (value) => String(value || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (c) => c.toUpperCase());

const stepLabel = (step) => {
  if (step.type === 'agent') return step.agent || step.name || 'Agent step';
  if (step.type === 'mcp_tool') return step.destination ? `Save to ${step.destination}` : (step.tool || 'Tool step');
  if (step.type === 'human_approval') return step.name || 'Human approval';
  return step.name || step.id || titleize(step.type);
};

const stepIcon = (step) => {
  if (step.type === 'human_approval') return FaShieldAlt;
  if (step.type === 'mcp_tool') return FaFolderOpen;
  if (step.type === 'agent') return FaRobot;
  return FaTasks;
};

const stepTypeLabel = (step) => {
  if (step.type === 'agent') return 'Draft prepared';
  if (step.type === 'mcp_tool') return 'File saved';
  if (step.type === 'human_approval') return 'Staff review';
  return titleize(step.type);
};

const FlowStatus = ({ flow }) => (
  <span className={`ap-status ${flow.ready ? 'ap-status-production' : 'ap-status-draft'}`}>
    {flow.ready ? <FaCheckCircle size={11} /> : <FaExclamationTriangle size={11} />}
    {readinessLabel(flow)}
  </span>
);

const VetPracticeDashboardPage = () => {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [activeFlowKey, setActiveFlowKey] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    api.get('/vet-practice/dashboard', { params: { variant: 'gp_full' } })
      .then((res) => {
        if (!cancelled) {
          setData(res.data);
          setActiveFlowKey(res.data?.flows?.[0]?.key || '');
        }
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
      { label: 'File stores', value: `${summary.storage_connected || 0}/${summary.storage_expected || 0}`, Icon: FaFolderOpen },
      { label: 'Flows ready', value: `${summary.flows_ready || 0}/${summary.flows_expected || 0}`, Icon: FaTasks },
      { label: 'Workflows', value: `${summary.workflows_installed || 0}/${summary.workflows_expected || 0}`, Icon: FaHeartbeat },
    ];
  }, [data?.summary]);

  const activeFlow = useMemo(() => {
    const flows = data?.flows || [];
    return flows.find((flow) => flow.key === activeFlowKey) || flows[0] || null;
  }, [activeFlowKey, data?.flows]);

  const launch = data?.launch_context || {};
  const specialistLanes = data?.specialist_lanes || [];

  const openWorkflow = (flow) => {
    if (flow?.workflow?.id) {
      navigate(`/workflows/builder/${flow.workflow.id}`);
      return;
    }
    navigate('/workflows');
  };

  const openAgent = (flow) => {
    if (flow?.primary_agent_id) {
      navigate(`/agents/${flow.primary_agent_id}`);
      return;
    }
    navigate('/agents');
  };

  return (
    <Layout>
      <div className="vet-practice-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">Veterinary Practice</h1>
            <p className="ap-page-subtitle">
              {data?.practice_name || 'Practice'} - file-based operating board for Dr. Angelo and Dr. Brett workflows
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
              <div className="ap-section-label">Launch Brief</div>
              <div className="vet-practice-brief-grid">
                <article className="ap-card">
                  <div className="ap-card-body">
                    <h3 className="ap-card-title"><FaUserMd /> Clinical leads</h3>
                    {(launch.lead_clinicians || []).map((lead) => (
                      <p className="ap-card-text vet-practice-brief-line" key={lead.name}>
                        <strong>{lead.name}</strong> {lead.focus}
                      </p>
                    ))}
                  </div>
                </article>
                <article className="ap-card">
                  <div className="ap-card-body">
                    <h3 className="ap-card-title"><FaMapMarkerAlt /> Locations</h3>
                    <div className="vet-practice-chip-list">
                      {(launch.locations || []).map((location) => (
                        <span className="ap-badge-outline" key={location}>{location}</span>
                      ))}
                    </div>
                  </div>
                </article>
                <article className="ap-card">
                  <div className="ap-card-body">
                    <h3 className="ap-card-title"><FaFileAlt /> Current sources</h3>
                    {(launch.mvp_sources || []).slice(0, 4).map((source) => (
                      <p className="ap-card-text vet-practice-brief-line" key={source}>{source}</p>
                    ))}
                  </div>
                </article>
                <article className="ap-card">
                  <div className="ap-card-body">
                    <h3 className="ap-card-title"><FaClipboardList /> Initial meetings</h3>
                    {(launch.initial_meetings || []).map((meeting) => (
                      <p className="ap-card-text vet-practice-brief-line" key={meeting.title}>
                        <strong>{meeting.title}</strong> {meeting.summary}
                      </p>
                    ))}
                  </div>
                </article>
              </div>
            </section>

            <section className="vet-practice-section">
              <div className="ap-section-label">Daily Work Queue</div>
              <div className="vet-practice-board">
                <div className="vet-practice-flow-rail" role="tablist" aria-label="Practice flows">
                  {(data.flows || []).map((flow) => (
                    <button
                      type="button"
                      role="tab"
                      aria-selected={activeFlow?.key === flow.key}
                      className={`vet-practice-flow-tab ${activeFlow?.key === flow.key ? 'active' : ''}`}
                      key={flow.key}
                      onClick={() => setActiveFlowKey(flow.key)}
                    >
                      <span>
                        <strong>{flow.name}</strong>
                        <small>{flow.primary_agent}</small>
                      </span>
                      <FlowStatus flow={flow} />
                    </button>
                  ))}
                </div>

                {activeFlow && (
                  <article className="ap-card vet-practice-room">
                    <div className="ap-card-body">
                      <div className="vet-practice-room__head">
                        <div>
                          <h2>{activeFlow.name}</h2>
                          <p>{activeFlow.description}</p>
                        </div>
                        <FlowStatus flow={activeFlow} />
                      </div>

                      <div className="vet-practice-room__actions">
                        <button type="button" className="ap-btn-secondary" onClick={() => openAgent(activeFlow)}>
                          <FaRobot size={12} /> Open Agent
                        </button>
                        <button type="button" className="ap-btn-primary" onClick={() => openWorkflow(activeFlow)}>
                          <FaPlayCircle size={12} /> Open Process
                        </button>
                      </div>

                      <div className="vet-practice-room__meta">
                        <span>{activeFlow.primary_agent}</span>
                        <span>{activeFlow.workflow_template}</span>
                        <span>{activeFlow.approval_required ? 'Review required' : 'Staff confirmed'}</span>
                      </div>

                      <div className="vet-practice-room-grid">
                        <section>
                          <h3 className="vet-practice-subhead">Work items</h3>
                          <div className="vet-practice-work-items">
                            {(activeFlow.sample_queue || []).map((item) => (
                              <article className="vet-practice-work-item" key={item.id}>
                                <div>
                                  <h4>{item.title}</h4>
                                  <p>{item.next_step}</p>
                                  <div className="vet-practice-flow__meta">
                                    <span>{item.source}</span>
                                    <span>{item.location}</span>
                                    <span>{item.priority}</span>
                                  </div>
                                </div>
                                <span className="ap-badge-outline">{item.status}</span>
                              </article>
                            ))}
                          </div>
                        </section>

                        <section>
                          <h3 className="vet-practice-subhead">Packet checklist</h3>
                          <ul className="vet-practice-checklist">
                            {(activeFlow.packet_checklist || []).map((item) => (
                              <li key={item}><FaCheckCircle /> {item}</li>
                            ))}
                          </ul>
                        </section>
                      </div>

                      <div className="vet-practice-room-grid vet-practice-room-grid--bottom">
                        <section>
                          <h3 className="vet-practice-subhead">How the packet is prepared</h3>
                          <ol className="vet-practice-step-list">
                            {(activeFlow.workflow_steps || []).map((step) => {
                              const Icon = stepIcon(step);
                              return (
                                <li key={`${step.index}-${step.id || step.name}`}>
                                  <Icon aria-hidden="true" />
                                  <span>
                                    <strong>{stepLabel(step)}</strong>
                                    <small>{stepTypeLabel(step)}</small>
                                  </span>
                                </li>
                              );
                            })}
                          </ol>
                        </section>

                        <section>
                          <h3 className="vet-practice-subhead">Review gate</h3>
                          <div className="vet-practice-review-gate">
                            <FaShieldAlt aria-hidden="true" />
                            <div>
                              <strong>{activeFlow.review_gate?.label || 'Staff review'}</strong>
                              <p>{activeFlow.review_gate?.reason}</p>
                              <span className="ap-badge-outline">
                                {activeFlow.review_gate?.enforced_by_workflow ? 'Built-in approval step' : activeFlow.review_gate?.reviewer}
                              </span>
                            </div>
                          </div>
                        </section>
                      </div>
                    </div>
                  </article>
                )}
              </div>
            </section>

            {specialistLanes.length > 0 && (
              <section className="vet-practice-section">
                <div className="ap-section-label">Specialist Lane</div>
                <div className="vet-practice-specialist-grid">
                  {specialistLanes.map((lane) => (
                    <article className="ap-card" key={lane.key}>
                      <div className="ap-card-body">
                        <div className="vet-practice-specialist-head">
                          <div>
                            <h3 className="ap-card-title">{lane.name}</h3>
                            <p className="ap-card-text">{lane.description}</p>
                          </div>
                          <span className="ap-badge-outline">{lane.lead_clinician}</span>
                        </div>
                        {(lane.sample_queue || []).map((item) => (
                          <div className="vet-practice-specialist-case" key={item.id}>
                            <strong>{item.title}</strong>
                            <span>{item.next_step}</span>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            )}

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
                          {agent.escalation_to && (
                            <span className="ap-badge-outline mt-2">Routes to {agent.escalation_to}</span>
                          )}
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
                <div className="ap-section-label">Practice Software Prep</div>
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
