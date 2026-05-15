// Shared SubNav tab definitions. One source of truth so the in-page
// tab strips on the merged surfaces (Alpha Control, Agent Fleet,
// Memory) stay aligned without each page re-declaring the same list.

export const alphaControlTabs = [
  { to: '/dashboard', label: 'Overview', end: true },
  { to: '/chat', label: 'Chat' },
];

export const agentFleetTabs = [
  { to: '/agents', label: 'Fleet', end: true },
  { to: '/insights/fleet-health', label: 'Health' },
  { to: '/insights/cost', label: 'Cost & Usage' },
];

export const memoryTabs = [
  { to: '/memory', label: 'Memory', end: true },
  { to: '/learning', label: 'Learning' },
];
