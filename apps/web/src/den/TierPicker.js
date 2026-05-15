import { useState } from 'react';

import { TIER_FEATURES, TIER_RANGE } from './tierFeatures';
import { useTier } from './useTier';

/**
 * Tier picker — explicit P3 (per design §4): the user chooses their tier,
 * the platform never auto-promotes. Six cards with the persona + summary
 * from `TIER_FEATURES`.
 */
export function TierPicker({ onChange }) {
  const [tier, setTier] = useTier();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const choose = async (next) => {
    if (next === tier) return;
    setSaving(true);
    setError(null);
    try {
      await setTier(next);
      onChange?.(next);
    } catch (e) {
      setError('Could not save tier. Please retry.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid="tier-picker" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 14, fontWeight: 600 }}>Den tier</div>
      {TIER_RANGE.map((t) => {
        const feat = TIER_FEATURES[t];
        const active = t === tier;
        return (
          <button
            key={t}
            type="button"
            onClick={() => choose(t)}
            disabled={saving}
            data-testid={`tier-picker-option-${t}`}
            style={{
              textAlign: 'left',
              padding: '8px 12px',
              border: active ? '1px solid #3a82f6' : '1px solid #2a2a2a',
              background: active ? 'rgba(58, 130, 246, 0.08)' : 'transparent',
              borderRadius: 6,
              color: '#e5e5e5',
              cursor: saving ? 'wait' : 'pointer',
            }}
          >
            <div style={{ fontWeight: 600 }}>
              Tier {t} — {feat.name}
            </div>
            <div style={{ fontSize: 12, color: '#9aa0a6', marginTop: 2 }}>
              {feat.description}
            </div>
          </button>
        );
      })}
      {error && (
        <div style={{ color: '#f87171', fontSize: 12 }}>{error}</div>
      )}
    </div>
  );
}

export default TierPicker;
