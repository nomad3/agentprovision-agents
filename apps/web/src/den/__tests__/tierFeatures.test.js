/**
 * Tests for the tier capability map.
 * Pure data — no React, no API.
 */
import { TIER_FEATURES, TIER_RANGE, getCapabilities } from '../tierFeatures';

describe('tierFeatures', () => {
  test('TIER_RANGE covers 0..5 in order', () => {
    expect(TIER_RANGE).toEqual([0, 1, 2, 3, 4, 5]);
  });

  test('every tier has all capability keys defined', () => {
    const required = [
      'name', 'description',
      'showRail', 'showRightPanel', 'showDrawer',
      'showPlanStepper', 'showPalette', 'showAutoQualityScore',
      'showWorkflowEditor', 'showSkillAuthor', 'showPolicyEditor',
      'allowedRailIcons',
    ];
    for (const tier of TIER_RANGE) {
      const feat = TIER_FEATURES[tier];
      for (const key of required) {
        expect(feat).toHaveProperty(key);
      }
    }
  });

  test('higher tiers strictly add rail icons to lower tiers (monotonic)', () => {
    const t1 = new Set(TIER_FEATURES[1].allowedRailIcons);
    const t2 = new Set(TIER_FEATURES[2].allowedRailIcons);
    const t3 = new Set(TIER_FEATURES[3].allowedRailIcons);
    const t4 = new Set(TIER_FEATURES[4].allowedRailIcons);
    const t5 = new Set(TIER_FEATURES[5].allowedRailIcons);

    [...t1].forEach((i) => expect(t2.has(i)).toBe(true));
    [...t2].forEach((i) => expect(t3.has(i)).toBe(true));
    [...t3].forEach((i) => expect(t4.has(i)).toBe(true));
    [...t4].forEach((i) => expect(t5.has(i)).toBe(true));
  });

  test('tier 0 has minimal affordances (just chat)', () => {
    const feat = TIER_FEATURES[0];
    expect(feat.showRail).toBe(false);
    expect(feat.showRightPanel).toBe(false);
    expect(feat.showDrawer).toBe(false);
    expect(feat.allowedRailIcons).toEqual([]);
  });

  test('tier 4 unlocks the drawer + auto-quality score', () => {
    const feat = TIER_FEATURES[4];
    expect(feat.showDrawer).toBe(true);
    expect(feat.showAutoQualityScore).toBe(true);
  });

  test('tier 5 unlocks god-mode editors', () => {
    const feat = TIER_FEATURES[5];
    expect(feat.showWorkflowEditor).toBe(true);
    expect(feat.showSkillAuthor).toBe(true);
    expect(feat.showPolicyEditor).toBe(true);
  });

  test('getCapabilities clamps out-of-range tier values to 0..5', () => {
    expect(getCapabilities(-1)).toBe(TIER_FEATURES[0]);
    expect(getCapabilities(99)).toBe(TIER_FEATURES[5]);
    expect(getCapabilities('not-a-number')).toBe(TIER_FEATURES[0]);
    expect(getCapabilities(null)).toBe(TIER_FEATURES[0]);
    expect(getCapabilities(undefined)).toBe(TIER_FEATURES[0]);
  });

  test('getCapabilities returns the right tier for valid input', () => {
    expect(getCapabilities(3)).toBe(TIER_FEATURES[3]);
    expect(getCapabilities('2')).toBe(TIER_FEATURES[2]); // coerced from string
  });
});
