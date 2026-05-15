import {
  FaComments,
  FaRobot,
  FaDatabase,
  FaPuzzlePiece,
  FaProjectDiagram,
  FaPlug,
} from 'react-icons/fa';
import './ActivityBar.css';

const ICONS = [
  { id: 'chat', Icon: FaComments, label: 'Chat' },
  { id: 'agents', Icon: FaRobot, label: 'Agents' },
  { id: 'memory', Icon: FaDatabase, label: 'Memory' },
  { id: 'skills', Icon: FaPuzzlePiece, label: 'Skills' },
  { id: 'workflows', Icon: FaProjectDiagram, label: 'Workflows' },
  { id: 'integrations', Icon: FaPlug, label: 'Integrations' },
];

const ActivityBar = ({ active, onActivate }) => (
  <div className="ap-activitybar">
    {ICONS.map(({ id, Icon, label }) => (
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
    ))}
  </div>
);

export default ActivityBar;
