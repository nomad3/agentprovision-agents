import { NavLink } from 'react-router-dom';
import './SubNav.css';

const SubNav = ({ tabs }) => (
  <nav className="ap-subnav" aria-label="Section tabs">
    {tabs.map((tab) => (
      <NavLink
        key={tab.to}
        to={tab.to}
        end={tab.end}
        className={({ isActive }) => `ap-subnav-link${isActive ? ' active' : ''}`}
      >
        {tab.label}
      </NavLink>
    ))}
  </nav>
);

export default SubNav;
