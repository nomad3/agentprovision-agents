import { useTranslation } from 'react-i18next';
import {
  FaComments,
  FaRobot,
  FaDatabase,
  FaPuzzlePiece,
  FaProjectDiagram,
  FaPlug,
} from 'react-icons/fa';
import './ActivityBar.css';

// Each entry: id, icon component, i18n key + English fallback. Resolved
// via the `common` namespace so the labels participate in i18n alongside
// the sidebar entries in Layout.js.
const ICONS = [
  { id: 'chat', Icon: FaComments, key: 'sidebar.chat', fallback: 'Chat' },
  { id: 'agents', Icon: FaRobot, key: 'sidebar.agentFleet', fallback: 'Agents' },
  { id: 'memory', Icon: FaDatabase, key: 'sidebar.memory', fallback: 'Memory' },
  { id: 'skills', Icon: FaPuzzlePiece, key: 'sidebar.skills', fallback: 'Skills' },
  { id: 'workflows', Icon: FaProjectDiagram, key: 'sidebar.workflows', fallback: 'Workflows' },
  { id: 'integrations', Icon: FaPlug, key: 'sidebar.integrations', fallback: 'Integrations' },
];

const ActivityBar = ({ active, onActivate }) => {
  const { t } = useTranslation('common');
  return (
    <div className="ap-activitybar">
      {ICONS.map(({ id, Icon, key, fallback }) => {
        const label = t(key, fallback);
        return (
          <button
            key={id}
            type="button"
            className={`ap-activitybar-btn ${active === id ? 'active' : ''}`}
            title={label}
            aria-label={label}
            aria-pressed={active === id}
            onClick={() => onActivate(id)}
          >
            <Icon size={18} />
            <span className="ap-activitybar-label">{label}</span>
          </button>
        );
      })}
    </div>
  );
};

export default ActivityBar;
