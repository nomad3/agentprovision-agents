import { useCallback, useEffect, useState } from 'react';

import api from '../utils/api';
import { getCapabilities } from './tierFeatures';

/**
 * Read the user's Alpha Control Plane Den tier (0..5).
 *
 * On mount: returns the JWT-cached tier instantly (no flicker), then
 * confirms with `/api/v1/users/me/den-tier` to handle stale JWTs.
 *
 * setTier() persists the change server-side and updates local state.
 * The next JWT refresh carries the new value for subsequent reloads.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §4
 */

function tierFromJwt() {
  try {
    const token = localStorage.getItem('access_token');
    if (!token) return 0;
    const payloadB64 = token.split('.')[1];
    if (!payloadB64) return 0;
    // base64url → base64
    const b64 = payloadB64.replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const decoded = JSON.parse(atob(padded));
    const raw = decoded?.den_tier;
    const tier = Number(raw);
    return Number.isInteger(tier) && tier >= 0 && tier <= 5 ? tier : 0;
  } catch {
    return 0;
  }
}

export function useTier() {
  const [tier, setTierState] = useState(tierFromJwt);

  useEffect(() => {
    let cancelled = false;
    api.get('/users/me/den-tier')
      .then((res) => {
        if (cancelled) return;
        const next = Number(res.data?.tier);
        if (Number.isInteger(next) && next >= 0 && next <= 5) {
          setTierState(next);
        }
      })
      .catch(() => {
        // Stay with the JWT value — likely a transient API hiccup.
      });
    return () => { cancelled = true; };
  }, []);

  const setTier = useCallback(async (next) => {
    const clamped = Math.max(0, Math.min(5, Number(next) || 0));
    await api.put('/users/me/den-tier', { tier: clamped });
    setTierState(clamped);
    // Best-effort JWT refresh so subsequent reloads see the new tier
    // without round-tripping to /users/me/den-tier first.
    try { await api.post('/auth/refresh'); } catch { /* not critical */ }
  }, []);

  return [tier, setTier, getCapabilities(tier)];
}
