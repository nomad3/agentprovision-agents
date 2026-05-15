import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import './SubNav.css';

// `ariaLabelKey` is a common-namespace i18n key, defaulted to a generic
// label. Distinct keys per SubNav instance let screen-reader users
// distinguish the three instances (Alpha Control, Agent Fleet, Memory)
// by landmark instead of hearing identical labels.
const SubNav = ({ tabs, ariaLabelKey = 'subnav.ariaDefault', ariaLabelFallback = 'Section tabs' }) => {
  const { t } = useTranslation('common');
  return (
    <nav className="ap-subnav" aria-label={t(ariaLabelKey, ariaLabelFallback)}>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => `ap-subnav-link${isActive ? ' active' : ''}`}
        >
          {tab.labelKey ? t(tab.labelKey, tab.label) : tab.label}
        </NavLink>
      ))}
    </nav>
  );
};

export default SubNav;
