import { useMemo, useState } from 'react';
import { Badge, Dropdown, Nav, OverlayTrigger, Tooltip } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import {
  FaSignOutAlt as BoxArrowRight,
  FaBuilding as BuildingFill,
  FaDatabase as DatabaseFill,
  FaCog as GearFill,
  FaHome as HouseDoorFill,
  FaMoon as MoonFill,
  FaUserCircle as PersonCircle,
  FaPlug as PlugFill,
  FaProjectDiagram as ProjectDiagramFill,
  FaRobot as Robot,
  FaSun as SunFill,
  FaPuzzlePiece as PuzzlePiece,
  FaHeartbeat as HeartbeatFill,
  FaAngleDoubleLeft,
  FaAngleDoubleRight,
} from 'react-icons/fa';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../App';
import { useLunaPresence } from '../context/LunaPresenceContext';
import { useTheme } from '../context/ThemeContext';
// LunaAvatar removed
import LunaStateBadge from './luna/LunaStateBadge';
import NotificationBell from './NotificationBell';
import './Layout.css';

const _LS_SIDEBAR_PINNED = 'brand.sidebar.pinned';
const _readPinned = () => {
  try { return localStorage.getItem(_LS_SIDEBAR_PINNED) === 'true'; } catch { return false; }
};
const _writePinned = (v) => {
  try { localStorage.setItem(_LS_SIDEBAR_PINNED, String(!!v)); } catch { /* quota */ }
};

const Layout = ({ children }) => {
  // Sidebar collapse state. Default collapsed → icon-only ~56 px rail
  // (VSCode / Cursor / Antigravity pattern). Hovering peeks the full
  // labels out as an overlay; the pin button locks it open ("pinned").
  const [pinned, setPinned] = useState(_readPinned);
  const [hovering, setHovering] = useState(false);
  const togglePinned = () => {
    setPinned((prev) => {
      const next = !prev;
      _writePinned(next);
      return next;
    });
  };
  const expanded = pinned || hovering;

  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t, i18n } = useTranslation('common');
  const { theme, toggleTheme } = useTheme();
  const lunaCtx = useLunaPresence();
  const lunaState = lunaCtx?.presence?.state || 'idle';
  const lunaMood = lunaCtx?.presence?.mood || 'calm';

  const currentLanguage = (i18n.language || 'en').split('-')[0];
  const languageOptions = useMemo(
    () => [
      { code: 'en', label: t('language.english') },
      { code: 'es', label: t('language.spanish') },
    ],
    [t, i18n.language]
  );

  const handleLogout = () => {
    auth.logout();
    navigate('/login');
  };

  const handleLanguageChange = (code) => {
    i18n.changeLanguage(code);
  };

  // Navigation structure — consolidated into the Alpha Control Center IA:
  // Integrations leads (most-used surface); Dashboard absorbs AI Chat as a tab;
  // Agent Fleet absorbs Fleet Health + Cost & Usage via SubNav inside the page;
  // Memory absorbs Learning via SubNav inside the page.
  const navSections = [
    {
      title: null,
      items: [
        { path: '/integrations', icon: PlugFill, label: t('sidebar.integrations'), description: t('sidebar_desc.integrations') },
        { path: '/dashboard', icon: HouseDoorFill, label: t('sidebar.alphaControl', 'Alpha Control'), description: t('sidebar_desc.alphaControl', 'Command center + chat with your agents') },
      ]
    },
    {
      title: t('sidebar.aiOperations'),
      items: [
        { path: '/agents', icon: Robot, label: t('sidebar.agentFleet', 'Agent Fleet'), description: t('sidebar_desc.agentFleet', 'Fleet, health, and cost in one view') },
        { path: '/workflows', icon: ProjectDiagramFill, label: t('sidebar.workflows'), description: t('sidebar_desc.workflows') },
        { path: '/memory', icon: DatabaseFill, label: t('sidebar.memory'), description: t('sidebar_desc.memoryLearning', 'Memory + learning') },
        { path: '/skills', icon: PuzzlePiece, label: t('sidebar.skills'), description: t('sidebar_desc.skills') },
      ]
    },
    {
      title: t('sidebar.admin'),
      items: [
        { path: '/tenants', icon: BuildingFill, label: t('sidebar.organizations'), description: t('sidebar_desc.organizations') },
        { path: '/settings', icon: GearFill, label: t('sidebar.settings'), description: t('sidebar_desc.settings') },
        // Tenant Health is superuser-only on the backend; hide the
        // link entirely for regular tenant admins so it doesn't read
        // as broken when they click and get a 403.
        ...(auth.user?.is_superuser
          ? [{ path: '/admin/tenant-health', icon: HeartbeatFill, label: t('sidebar.tenantHealth', 'Tenant Health'), description: t('sidebar_desc.tenantHealth', 'Cross-tenant superuser triage') }]
          : []),
      ]
    }
  ];

  // Active matching is path-prefix aware so sub-routes (e.g. /insights/fleet-health
  // under Agent Fleet, /learning under Memory) keep the parent nav highlighted.
  // We list exact Agent-Fleet siblings rather than a blanket `/insights/` prefix —
  // /insights/collaborations belongs to Coalition Replay, not the Fleet group.
  const isActive = (path) => {
    if (path === '/dashboard') return location.pathname === '/dashboard' || location.pathname === '/chat';
    if (path === '/agents') {
      const p = location.pathname;
      return p.startsWith('/agents') || p === '/insights/fleet-health' || p === '/insights/cost';
    }
    if (path === '/memory') return location.pathname === '/memory' || location.pathname === '/learning';
    return location.pathname === path;
  };

  return (
    <div className={`layout-container${pinned ? '' : ' sidebar-collapsed'}${expanded ? ' sidebar-expanded' : ''}`}>
      {/* Glassmorphic Sidebar */}
      <div
        className="sidebar-glass"
        onMouseEnter={() => setHovering(true)}
        onMouseLeave={() => setHovering(false)}
      >
        <div className="sidebar-header">
          <div className="d-flex align-items-center justify-content-between">
            <Link to="/dashboard" className="brand-link">
              <div className="d-flex flex-column">
                <span className="brand-text">{t('brand')}</span>
                <LunaStateBadge state={lunaState} size="xs" />
              </div>
            </Link>
            <div className="d-flex align-items-center gap-1 sidebar-header-actions">
              <button
                type="button"
                className="theme-toggle"
                onClick={togglePinned}
                aria-label={pinned ? 'Collapse sidebar' : 'Pin sidebar open'}
                title={pinned ? 'Collapse sidebar' : 'Pin sidebar open'}
              >
                {pinned ? <FaAngleDoubleLeft size={14} /> : <FaAngleDoubleRight size={14} />}
              </button>
              <NotificationBell />
              <button
                className="theme-toggle"
                onClick={toggleTheme}
                aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
                title={theme === 'light' ? 'Dark mode' : 'Light mode'}
              >
                {theme === 'light' ? <MoonFill size={16} /> : <SunFill size={16} />}
              </button>
            </div>
          </div>
        </div>

        <Nav className="flex-column sidebar-nav">
          {navSections.map((section, sectionIndex) => (
            <div key={`section-${sectionIndex}`} className="nav-section">
              {section.title && (
                <div className="nav-section-header">
                  <span className="nav-section-title">{section.title}</span>
                </div>
              )}
              {section.items.map((item) => {
                const Icon = item.icon;
                return (
                  <OverlayTrigger
                    key={item.path}
                    placement="right"
                    delay={{ show: 500, hide: 0 }}
                    overlay={<Tooltip id={`tooltip-${item.path}`}>{item.description}</Tooltip>}
                  >
                    <Nav.Link
                      as={Link}
                      to={item.path}
                      className={`sidebar-nav-link ${isActive(item.path) ? 'active' : ''}`}
                      aria-label={item.label}
                    >
                      <Icon className="nav-icon" size={20} />
                      <span className="nav-label">{item.label}</span>
                      {item.badge && (
                        <Badge bg="primary" className="nav-badge">{item.badge}</Badge>
                      )}
                    </Nav.Link>
                  </OverlayTrigger>
                );
              })}
            </div>
          ))}
        </Nav>

        <div className="sidebar-footer">
          <Dropdown drop="up" className="w-100">
            <Dropdown.Toggle variant="link" className="user-dropdown-toggle w-100">
              <div className="d-flex align-items-center gap-2">
                <PersonCircle size={32} className="text-primary" />
                <div className="flex-grow-1 text-start">
                  <div className="user-email">{auth.user?.email || t('layout.guest')}</div>
                  <div className="user-role">{t('sidebar.administrator')}</div>
                </div>
              </div>
            </Dropdown.Toggle>
            <Dropdown.Menu className="w-100">
              <Dropdown.Header>{t('language.label')}</Dropdown.Header>
              {languageOptions.map(({ code, label }) => (
                <Dropdown.Item
                  key={code}
                  active={currentLanguage === code}
                  onClick={() => handleLanguageChange(code)}
                >
                  {label}
                </Dropdown.Item>
              ))}
              <Dropdown.Divider />
              <Dropdown.Item onClick={handleLogout}>
                <BoxArrowRight className="me-2" /> {t('layout.logout')}
              </Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="main-content">
        <div className="content-wrapper">
          {children}
        </div>
      </div>
    </div>
  );
};

export default Layout;
