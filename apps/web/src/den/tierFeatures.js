/**
 * Tier capability map for the Alpha Control Plane Den.
 *
 * Each tier unlocks more of the den UI. Same shell skeleton at
 * every tier — only the populated content density changes. Stored on
 * the user's profile as `user_preferences.alpha_den_tier` (see
 * apps/api/app/services/user_tier.py), accessed via `useTier()` here.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §4
 */

export const TIER_FEATURES = {
  0: {
    name: 'First touch',
    description: 'Just chat. The simplest possible den — talk to alpha and get answers.',
    showRail: false,
    showRightPanel: false,
    showDrawer: false,
    showPlanStepper: false,
    showPalette: false,
    showAutoQualityScore: false,
    showWorkflowEditor: false,
    showSkillAuthor: false,
    showPolicyEditor: false,
    allowedRailIcons: [],
  },
  1: {
    name: 'Connected',
    description: 'Integrations live. Tool calls render inline as alpha uses them.',
    showRail: true,
    showRightPanel: false,
    showDrawer: false,
    showPlanStepper: false,
    showPalette: false,
    showAutoQualityScore: false,
    showWorkflowEditor: false,
    showSkillAuthor: false,
    showPolicyEditor: false,
    allowedRailIcons: ['integrations', 'memory'],
  },
  2: {
    name: 'Multi-agent',
    description: 'Plan stepper + active-agent view during coalitions.',
    showRail: true,
    showRightPanel: true,
    showDrawer: false,
    showPlanStepper: true,
    showPalette: false,
    showAutoQualityScore: false,
    showWorkflowEditor: false,
    showSkillAuthor: false,
    showPolicyEditor: false,
    allowedRailIcons: ['integrations', 'memory', 'projects'],
  },
  3: {
    name: 'Workspace',
    description: 'Full resource browsers + Cmd+K palette + pinning.',
    showRail: true,
    showRightPanel: true,
    showDrawer: false,
    showPlanStepper: true,
    showPalette: true,
    showAutoQualityScore: false,
    showWorkflowEditor: false,
    showSkillAuthor: false,
    showPolicyEditor: false,
    allowedRailIcons: ['integrations', 'memory', 'projects', 'leads', 'datasets', 'experiments', 'entities', 'skills'],
  },
  4: {
    name: 'Operator',
    description: 'Fleet, deployments, experiments + live drawer on by default.',
    showRail: true,
    showRightPanel: true,
    showDrawer: true,
    showPlanStepper: true,
    showPalette: true,
    showAutoQualityScore: true,
    showWorkflowEditor: false,
    showSkillAuthor: false,
    showPolicyEditor: false,
    allowedRailIcons: ['integrations', 'memory', 'projects', 'leads', 'datasets', 'experiments', 'entities', 'skills', 'fleet', 'deployments', 'rl'],
  },
  5: {
    name: 'God',
    description: 'Customising the platform — workflows, skills, alpha policy.',
    showRail: true,
    showRightPanel: true,
    showDrawer: true,
    showPlanStepper: true,
    showPalette: true,
    showAutoQualityScore: true,
    showWorkflowEditor: true,
    showSkillAuthor: true,
    showPolicyEditor: true,
    allowedRailIcons: ['integrations', 'memory', 'projects', 'leads', 'datasets', 'experiments', 'entities', 'skills', 'fleet', 'deployments', 'rl'],
  },
};

export const TIER_RANGE = [0, 1, 2, 3, 4, 5];

/**
 * Return the capability map for a given tier. Clamps out-of-range
 * values to {0..5} so the den never crashes on a corrupt JWT.
 */
export function getCapabilities(tier) {
  const clamped = Math.max(0, Math.min(5, Number(tier) || 0));
  return TIER_FEATURES[clamped];
}
