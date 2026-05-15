// Shared SubNav tab definitions. One source of truth so the in-page
// tab strips on the merged surfaces (Alpha Control, Agent Fleet,
// Memory) stay aligned without each page re-declaring the same list.
//
// Each tab carries an i18n key + English fallback so SubNav can resolve
// translations itself without each caller having to pull in the common
// namespace.

export const alphaControlTabs = [
  { to: '/dashboard', labelKey: 'subnav.overview', label: 'Overview', end: true },
  { to: '/chat', labelKey: 'subnav.chat', label: 'Chat' },
];

export const agentFleetTabs = [
  { to: '/agents', labelKey: 'subnav.fleet', label: 'Fleet', end: true },
  { to: '/insights/fleet-health', labelKey: 'subnav.health', label: 'Health' },
  { to: '/insights/cost', labelKey: 'subnav.costUsage', label: 'Cost & Usage' },
];

export const memoryTabs = [
  { to: '/memory', labelKey: 'subnav.memory', label: 'Memory', end: true },
  { to: '/learning', labelKey: 'subnav.learning', label: 'Learning' },
];

// aria-label keys for each SubNav instance — passed by the page so
// screen-reader users hear a distinct landmark per instance.
export const ARIA_LABEL_KEYS = {
  alphaControl: 'subnav.ariaAlphaControl',
  agentFleet: 'subnav.ariaAgentFleet',
  memory: 'subnav.ariaMemory',
};
