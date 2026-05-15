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
  { id: 'chat', Icon: FaComments, label: 'Chat (⌘⇧C)' },
  { id: 'agents', Icon: FaRobot, label: 'Agents (⌘⇧A)' },
  { id: 'memory', Icon: FaDatabase, label: 'Memory (⌘⇧M)' },
  { id: 'skills', Icon: FaPuzzlePiece, label: 'Skills (⌘⇧K)' },
  { id: 'workflows', Icon: FaProjectDiagram, label: 'Workflows (⌘⇧W)' },
  { id: 'integrations', Icon: FaPlug, label: 'Integrations (⌘⇧I)' },
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
      </button>
    ))}
  </div>
);

export default ActivityBar;
