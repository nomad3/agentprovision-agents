import { Dropdown } from 'react-bootstrap';
import { FaUser, FaSignOutAlt, FaColumns } from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import './TitleBar.css';

const TitleBar = ({ tabsApi, onToggleRight }) => {
  const auth = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    auth.logout();
    navigate('/login');
  };

  const handleSettings = () => navigate('/settings');

  return (
    <div className="ap-titlebar">
      <div className="ap-titlebar-brand">
        <span className="ap-titlebar-brand-name">agentprovision</span>
        <span className="ap-titlebar-divider">·</span>
        <span className="ap-titlebar-session">
          {tabsApi.activeTab?.title || 'No session selected'}
        </span>
      </div>
      <div className="ap-titlebar-actions">
        <button
          type="button"
          className="ap-titlebar-btn"
          onClick={onToggleRight}
          title="Toggle Agent Activity panel (⌘⌥B)"
          aria-label="Toggle Agent Activity panel"
        >
          <FaColumns size={13} />
        </button>
        <Dropdown align="end">
          <Dropdown.Toggle variant="link" className="ap-titlebar-user">
            <FaUser size={12} />
            <span className="ap-titlebar-user-email">{auth.user?.email || 'Guest'}</span>
          </Dropdown.Toggle>
          <Dropdown.Menu>
            <Dropdown.Item onClick={handleSettings}>Settings</Dropdown.Item>
            <Dropdown.Divider />
            <Dropdown.Item onClick={handleLogout}>
              <FaSignOutAlt className="me-2" size={12} /> Logout
            </Dropdown.Item>
          </Dropdown.Menu>
        </Dropdown>
      </div>
    </div>
  );
};

export default TitleBar;
