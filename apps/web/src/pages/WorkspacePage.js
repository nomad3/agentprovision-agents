import { useEffect, useMemo, useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import {
  FaCheckCircle,
  FaClipboardList,
  FaExclamationTriangle,
  FaFileAlt,
  FaFilePdf,
  FaFolderOpen,
  FaMapMarkerAlt,
  FaPlug,
  FaRobot,
  FaShieldAlt,
  FaTasks,
  FaUserMd,
} from 'react-icons/fa';
import { useNavigate, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import { formatApiError } from '../services/apiError';
import workspaceService from '../services/workspaces';
import './WorkspacePage.css';

const stateLabel = (state) => {
  if (state === 'ready') return 'Ready';
  if (state === 'empty') return 'No work yet';
  if (state === 'setup_required') return 'Needs setup';
  if (state === 'missing_permission') return 'No access';
  if (state === 'unsupported') return 'Unavailable';
  return 'Error';
};

const stateClass = (state) => {
  if (state === 'ready') return 'ap-status-production';
  if (state === 'empty') return 'ap-status-staging';
  if (state === 'setup_required') return 'ap-status-draft';
  return 'ap-status-deprecated';
};

const StatusPill = ({ state }) => (
  <span className={`ap-status ${stateClass(state)}`}>
    <span className="ap-status-dot" />
    {stateLabel(state)}
  </span>
);

const titleize = (value) => String(value || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (c) => c.toUpperCase());

const stepLabel = (step) => {
  if (step.type === 'agent') return step.agent || step.name || 'Agent step';
  if (step.type === 'mcp_tool') return step.destination ? `Save to ${step.destination}` : (step.tool || 'File step');
  if (step.type === 'human_approval') return step.name || 'Human review';
  return step.name || step.id || titleize(step.type);
};

const StepIcon = ({ type }) => {
  if (type === 'human_approval') return <FaShieldAlt aria-hidden="true" />;
  if (type === 'mcp_tool') return <FaFolderOpen aria-hidden="true" />;
  if (type === 'agent') return <FaRobot aria-hidden="true" />;
  return <FaTasks aria-hidden="true" />;
};

const WidgetShell = ({ widget, title, children }) => (
  <article className={`ap-card ws-widget ws-widget--${widget.state}`}>
    <div className="ap-card-body">
      <div className="ws-widget__head">
        <div>
          <h2 className="ap-card-title">{title}</h2>
          {widget.example && <span className="ap-badge-outline">Example preview</span>}
        </div>
        <StatusPill state={widget.state} />
      </div>
      {widget.setup_blockers?.length ? (
        <div className="ws-blockers">
          {widget.setup_blockers.map((blocker) => (
            <div key={blocker}><FaExclamationTriangle /> {blocker}</div>
          ))}
        </div>
      ) : null}
      {children}
    </div>
  </article>
);

const LaunchBriefWidget = ({ widget, definition }) => {
  const launch = widget.data?.launch_context || {};
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-brief-grid">
        <section>
          <h3><FaUserMd /> Clinical leads</h3>
          {(launch.lead_clinicians || []).map((lead) => (
            <p key={lead.name}><strong>{lead.name}</strong>{lead.focus}</p>
          ))}
        </section>
        <section>
          <h3><FaMapMarkerAlt /> Locations</h3>
          <div className="ws-chip-list">
            {(launch.locations || []).map((location) => (
              <span className="ap-badge-outline" key={location}>{location}</span>
            ))}
          </div>
        </section>
        <section>
          <h3><FaFileAlt /> Current sources</h3>
          {(launch.mvp_sources || []).map((source) => <p key={source}>{source}</p>)}
        </section>
        <section>
          <h3><FaClipboardList /> Initial meetings</h3>
          {(launch.initial_meetings || []).map((meeting) => (
            <p key={meeting.title}><strong>{meeting.title}</strong>{meeting.summary}</p>
          ))}
        </section>
      </div>
    </WidgetShell>
  );
};

const WorkQueueWidget = ({ widget, definition }) => {
  const items = widget.data?.items || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-work-grid">
        {items.map((item) => (
          <article className="ws-work-item" key={`${item.flow_key}-${item.id}`}>
            <div>
              <h3>{item.title}</h3>
              <p>{item.next_step}</p>
              <div className="ws-meta">
                <span>{item.flow_name}</span>
                <span>{item.location}</span>
                <span>{item.priority}</span>
              </div>
            </div>
            <span className="ap-badge-outline">{item.status}</span>
          </article>
        ))}
      </div>
    </WidgetShell>
  );
};

const FlowBoardWidget = ({ widget, definition }) => {
  const flows = widget.data?.flows || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-flow-list">
        {flows.map((flow) => (
          <section className="ws-flow" key={flow.key}>
            <div className="ws-flow__head">
              <div>
                <h3>{flow.name}</h3>
                <p>{flow.description}</p>
              </div>
              <StatusPill state={flow.ready ? 'ready' : 'setup_required'} />
            </div>
            <div className="ws-flow__grid">
              <div>
                <h4>Packet checklist</h4>
                <ul className="ws-check-list">
                  {(flow.packet_checklist || []).map((item) => (
                    <li key={item}><FaCheckCircle /> {item}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h4>Preparation steps</h4>
                <ol className="ws-step-list">
                  {(flow.workflow_steps || []).slice(0, 6).map((step) => (
                    <li key={`${flow.key}-${step.index}-${step.id || step.name}`}>
                      <StepIcon type={step.type} />
                      <span>{stepLabel(step)}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};

const SourcePacketsWidget = ({ widget, definition }) => {
  const sources = widget.data?.sources || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-source-list">
        {sources.map((source) => (
          <section className="ws-source-card" key={`${source.provider}-${source.folder_id || source.label}`}>
            <div className="ws-source-card__head">
              <div>
                <h3><FaFolderOpen /> {source.folder_name || source.label}</h3>
                <p>{source.account_email || source.provider}</p>
              </div>
              <StatusPill state={source.state === 'ready' ? 'ready' : source.state || 'empty'} />
            </div>
            <div className="ws-meta">
              <span>{source.counts?.files || 0} files</span>
              <span>{source.counts?.pdfs || 0} PDFs</span>
              {source.label && <span>{source.label}</span>}
            </div>
            <div className="ws-source-files">
              {(source.files || []).map((file) => (
                <div className="ws-source-file" key={file.id || file.name}>
                  {file.kind === 'pdf' ? <FaFilePdf aria-hidden="true" /> : <FaFileAlt aria-hidden="true" />}
                  <span>
                    <strong>{file.name}</strong>
                    <small>{file.kind === 'pdf' ? 'PDF packet file' : titleize(file.kind)}</small>
                  </span>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};

const ReviewGatesWidget = ({ widget, definition }) => {
  const gates = widget.data?.gates || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-gate-list">
        {gates.map((gate) => (
          <section className="ws-gate" key={gate.flow_key}>
            <FaShieldAlt aria-hidden="true" />
            <div>
              <h3>{gate.review_gate?.label || gate.flow_name}</h3>
              <p>{gate.review_gate?.reason}</p>
              <span className="ap-badge-outline">
                {gate.review_gate?.enforced_by_workflow ? 'Built-in approval' : gate.review_gate?.reviewer}
              </span>
            </div>
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};

const AgentFleetWidget = ({ widget, definition }) => {
  const agents = widget.data?.agents || [];
  const navigate = useNavigate();
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-agent-list">
        {agents.map((agent) => (
          <button
            type="button"
            className="ws-agent-row"
            key={agent.name}
            onClick={() => agent.id ? navigate(`/agents/${agent.id}`) : navigate('/agents')}
          >
            <span>
              <strong>{agent.name}</strong>
              <small>{agent.description}</small>
            </span>
            <StatusPill state={agent.present ? 'ready' : 'setup_required'} />
          </button>
        ))}
      </div>
    </WidgetShell>
  );
};

const SystemReadinessWidget = ({ widget, definition }) => {
  const storage = widget.data?.storage || [];
  const systems = widget.data?.practice_systems || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-readiness-grid">
        {storage.map((store) => (
          <section className="ws-readiness-card" key={store.integration_name}>
            <h3>{store.display_name}</h3>
            <p>{store.account_email || 'Repository needed for packet work.'}</p>
            <StatusPill state={store.connected ? 'ready' : 'setup_required'} />
          </section>
        ))}
        {systems.map((system) => (
          <section className="ws-readiness-card" key={system.key}>
            <h3>{system.name}</h3>
            <p>{system.note}</p>
            <span className="ap-badge-outline">{system.status}</span>
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};

const ReferralLaneWidget = ({ widget, definition }) => {
  const lanes = widget.data?.lanes || [];
  return (
    <WidgetShell widget={widget} title={definition.title}>
      <div className="ws-referral-grid">
        {lanes.map((lane) => (
          <section className="ws-referral-card" key={lane.key}>
            <div className="ws-flow__head">
              <div>
                <h3>{lane.name}</h3>
                <p>{lane.description}</p>
              </div>
              <span className="ap-badge-outline">{lane.lead_clinician}</span>
            </div>
            {(lane.sample_queue || []).map((item) => (
              <div className="ws-referral-case" key={item.id}>
                <strong>{item.title}</strong>
                <span>{item.next_step}</span>
              </div>
            ))}
          </section>
        ))}
      </div>
    </WidgetShell>
  );
};

const GenericWidget = ({ widget, definition }) => (
  <WidgetShell widget={widget} title={definition.title}>
    <pre className="ws-json">{JSON.stringify(widget.data || {}, null, 2)}</pre>
  </WidgetShell>
);

const renderWidget = (widget, definition) => {
  if (definition.type === 'launch_brief') return <LaunchBriefWidget widget={widget} definition={definition} />;
  if (definition.type === 'work_queue') return <WorkQueueWidget widget={widget} definition={definition} />;
  if (definition.type === 'source_packets') return <SourcePacketsWidget widget={widget} definition={definition} />;
  if (definition.type === 'flow_board') return <FlowBoardWidget widget={widget} definition={definition} />;
  if (definition.type === 'review_gates') return <ReviewGatesWidget widget={widget} definition={definition} />;
  if (definition.type === 'agent_fleet') return <AgentFleetWidget widget={widget} definition={definition} />;
  if (definition.type === 'system_readiness') return <SystemReadinessWidget widget={widget} definition={definition} />;
  if (definition.type === 'referral_lane') return <ReferralLaneWidget widget={widget} definition={definition} />;
  return <GenericWidget widget={widget} definition={definition} />;
};

const WorkspacePage = () => {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setDetail(null);
    workspaceService.get(slug)
      .then((res) => {
        if (!cancelled) setDetail(res.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setDetail(null);
          setError(formatApiError(err, 'Workspace not found or not enabled for this tenant.'));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [slug]);

  const definitionsByKey = useMemo(() => {
    const widgets = detail?.descriptor?.widgets || [];
    return Object.fromEntries(widgets.map((widget) => [widget.key, widget]));
  }, [detail?.descriptor?.widgets]);

  const descriptor = detail?.descriptor;

  return (
    <Layout>
      <div className="workspace-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">{descriptor?.label || 'Workspace'}</h1>
            <p className="ap-page-subtitle">{descriptor?.description || 'Tenant workspace'}</p>
          </div>
          <div className="ap-page-actions">
            <button type="button" className="ap-btn-secondary" onClick={() => navigate('/integrations')}>
              <FaPlug size={12} /> Systems
            </button>
            <button type="button" className="ap-btn-secondary" onClick={() => navigate('/workflows')}>
              <FaTasks size={12} /> Processes
            </button>
            <button type="button" className="ap-btn-primary" onClick={() => navigate('/agents')}>
              <FaRobot size={12} /> Agents
            </button>
          </div>
        </header>

        {error && <Alert variant="warning">{error}</Alert>}

        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" size="sm" variant="primary" />
          </div>
        ) : detail ? (
          <div className="workspace-grid">
            {(detail.widgets || []).map((widget) => {
              const definition = definitionsByKey[widget.key] || { key: widget.key, title: titleize(widget.key), type: 'json' };
              return (
                <div
                  className={`workspace-grid__item workspace-grid__item--span-${definition.span || 1}`}
                  key={widget.key}
                >
                  {renderWidget(widget, definition)}
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </Layout>
  );
};

export default WorkspacePage;
