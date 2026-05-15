import { useNavigate } from 'react-router-dom';

const MemoryPanel = () => {
  const navigate = useNavigate();
  // Phase 1 keeps memory simple: deep links into existing /memory page
  // (which already has its own rich tabbed surface) plus /learning.
  const links = [
    { label: 'Overview', path: '/memory' },
    { label: 'Entities', path: '/memory?tab=entities' },
    { label: 'Relations', path: '/memory?tab=relations' },
    { label: 'Memories', path: '/memory?tab=memories' },
    { label: 'Episodes', path: '/memory?tab=episodes' },
    { label: 'Activity', path: '/memory?tab=activity' },
    { label: 'Import', path: '/memory?tab=import' },
    { label: 'Learning (RL)', path: '/learning' },
  ];
  return (
    <ul className="ap-sidebar-list">
      {links.map((l) => (
        <li key={l.path}>
          <button type="button" onClick={() => navigate(l.path)}>{l.label}</button>
        </li>
      ))}
    </ul>
  );
};

export default MemoryPanel;
