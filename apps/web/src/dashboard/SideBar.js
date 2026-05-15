import SessionsPanel from './panels/SessionsPanel';
import AgentsPanel from './panels/AgentsPanel';
import MemoryPanel from './panels/MemoryPanel';
import SkillsPanel from './panels/SkillsPanel';
import WorkflowsPanel from './panels/WorkflowsPanel';
import IntegrationsPanel from './panels/IntegrationsPanel';
import './SideBar.css';

const PANELS = {
  chat: { title: 'Chats', Panel: SessionsPanel },
  agents: { title: 'Agent Fleet', Panel: AgentsPanel },
  memory: { title: 'Memory', Panel: MemoryPanel },
  skills: { title: 'Skills', Panel: SkillsPanel },
  workflows: { title: 'Workflows', Panel: WorkflowsPanel },
  integrations: { title: 'Integrations', Panel: IntegrationsPanel },
};

const SideBar = ({ activity, tabsApi, collapsed }) => {
  if (collapsed) return <div className="ap-sidebar" aria-hidden="true" />;
  const entry = PANELS[activity] || PANELS.chat;
  const Panel = entry.Panel;
  return (
    <div className="ap-sidebar">
      <div className="ap-sidebar-header">
        <span className="ap-sidebar-title">{entry.title}</span>
      </div>
      <div className="ap-sidebar-body">
        <Panel tabsApi={tabsApi} />
      </div>
    </div>
  );
};

export default SideBar;
