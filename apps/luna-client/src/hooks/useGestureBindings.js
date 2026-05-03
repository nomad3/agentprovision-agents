/**
 * Loads, mutates, and persists the user's gesture binding set.
 * - On mount, fetches `/users/me/gesture-bindings`. Falls back to
 *   `DEFAULT_BINDINGS` if the API returns empty or fails.
 * - `upsert(b)`, `remove(id)`, `resetToDefaults()` write through to the API.
 * - `detectConflict(candidate)` returns true if another enabled binding shares
 *   the same gesture+scope.
 */
import { useCallback, useEffect, useState } from 'react';
import { getGestureBindings, saveGestureBindings } from '../api';
import { DEFAULT_BINDINGS } from '../components/gestures/defaults';

function sameGesture(a, b) {
  if (a.gesture.pose !== b.gesture.pose) return false;
  const am = a.gesture.motion || null;
  const bm = b.gesture.motion || null;
  if (!am && !bm) return a.scope === b.scope;
  if (!am || !bm) return false;
  if (am.kind !== bm.kind) return false;
  if (am.direction !== bm.direction) return false;
  return a.scope === b.scope;
}

export function useGestureBindings() {
  const [bindings, setBindings] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getGestureBindings();
        if (cancelled) return;
        const next = Array.isArray(res?.bindings) && res.bindings.length > 0
          ? res.bindings
          : DEFAULT_BINDINGS;
        setBindings(next);
      } catch (e) {
        if (cancelled) return;
        setError(e);
        setBindings(DEFAULT_BINDINGS);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const detectConflict = useCallback((candidate) => (
    bindings.some(
      (b) => b.id !== candidate.id && b.enabled && candidate.enabled && sameGesture(b, candidate),
    )
  ), [bindings]);

  const persist = useCallback(async (next) => {
    setBindings(next);
    try { await saveGestureBindings(next); } catch (e) { setError(e); }
  }, []);

  const upsert = useCallback(async (binding) => {
    const idx = bindings.findIndex((b) => b.id === binding.id);
    const next = idx >= 0
      ? bindings.map((b, i) => (i === idx ? binding : b))
      : [...bindings, binding];
    await persist(next);
  }, [bindings, persist]);

  const remove = useCallback(async (id) => {
    await persist(bindings.filter((b) => b.id !== id));
  }, [bindings, persist]);

  const resetToDefaults = useCallback(async () => {
    await persist(DEFAULT_BINDINGS);
  }, [persist]);

  return { bindings, loaded, error, detectConflict, upsert, remove, resetToDefaults };
}
