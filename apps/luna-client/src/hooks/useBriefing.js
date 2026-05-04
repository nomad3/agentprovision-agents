/**
 * useBriefing — fetches the conductor's overture/finale data on demand.
 * Caches the last result so opening the finale right after closing it
 * doesn't refetch.
 */
import { useCallback, useState } from 'react';
import { apiJson } from '../api';

export function useBriefing() {
  const [briefing, setBriefing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchBriefing = useCallback(async (sinceIso) => {
    setLoading(true);
    setError(null);
    try {
      const qs = sinceIso ? `?since=${encodeURIComponent(sinceIso)}` : '';
      const body = await apiJson(`/api/v1/fleet/briefing${qs}`);
      setBriefing(body);
      return body;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return { briefing, loading, error, fetchBriefing };
}
