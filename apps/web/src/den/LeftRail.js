import {
  FaPlus, FaPlug, FaBrain, FaProjectDiagram, FaUserFriends,
  FaDatabase, FaFlask, FaSitemap, FaCog, FaServer, FaCloudUploadAlt,
  FaChartLine,
} from 'react-icons/fa';

import styles from './DenShell.module.css';

/**
 * Left rail — icon strip of resource navigators.
 *
 * Icons rendered are controlled by `capabilities.allowedRailIcons`
 * (sourced from `TIER_FEATURES[tier]`). Tier 0 sees a single "+"
 * button (welcome / connect-something call to action); higher tiers
 * unlock more icons.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §3 → "Left rail"
 */

const ICON_FOR = {
  integrations: FaPlug,
  memory: FaBrain,
  projects: FaProjectDiagram,
  leads: FaUserFriends,
  datasets: FaDatabase,
  experiments: FaFlask,
  entities: FaSitemap,
  skills: FaCog,
  fleet: FaServer,
  deployments: FaCloudUploadAlt,
  rl: FaChartLine,
};

const LABEL_FOR = {
  integrations: 'Integrations',
  memory: 'Memory',
  projects: 'Projects',
  leads: 'Leads',
  datasets: 'Datasets',
  experiments: 'Experiments',
  entities: 'Entities',
  skills: 'Skills',
  fleet: 'Fleet',
  deployments: 'Deployments',
  rl: 'RL experiences',
};

export function LeftRail({ capabilities, onSelect, active }) {
  const icons = capabilities?.allowedRailIcons ?? [];

  if (icons.length === 0) {
    // Tier 0 — a single welcome "+" that nudges the user toward
    // connecting their first integration.
    return (
      <nav className={styles.rail} aria-label="Den navigation">
        <button
          type="button"
          className={styles.railIcon}
          aria-label="Connect an integration"
          title="Connect an integration"
          onClick={() => onSelect?.('integrations')}
        >
          <FaPlus />
        </button>
      </nav>
    );
  }

  return (
    <nav className={styles.rail} aria-label="Den navigation">
      {icons.map((key) => {
        const Icon = ICON_FOR[key];
        if (!Icon) return null;
        const className = active === key
          ? `${styles.railIcon} ${styles.railIconActive}`
          : styles.railIcon;
        return (
          <button
            key={key}
            type="button"
            className={className}
            aria-label={LABEL_FOR[key] || key}
            title={LABEL_FOR[key] || key}
            onClick={() => onSelect?.(key)}
          >
            <Icon />
          </button>
        );
      })}
    </nav>
  );
}

export default LeftRail;
