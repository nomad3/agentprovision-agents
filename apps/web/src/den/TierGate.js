import { useTier } from './useTier';

/**
 * Render `children` only if the user's tier meets `min`. Otherwise
 * render `fallback` (default: null = render nothing).
 *
 * Whole-component gating helper for the Alpha Control Plane Den.
 * For fine-grained gating inside a component, use the capabilities
 * map from `useTier()` directly.
 *
 * Example:
 *   <TierGate min={2}>
 *     <PlanStepper session={session} />
 *   </TierGate>
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §4 → "Tier gating mechanism"
 */
export function TierGate({ min, fallback = null, children }) {
  const [tier] = useTier();
  if (tier < min) return fallback;
  return children;
}

export default TierGate;
