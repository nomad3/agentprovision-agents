/**
 * Accountable-learning commitment + learning-artifact API client.
 *
 * Thin function-per-endpoint surface over the tenant-scoped routes added by the
 * Accountable Learning & Commitment System (plan 2026-06-08). The proof gate,
 * red-flag killswitch, and tenant isolation all live server-side — this client
 * never bypasses them. Backend:
 *   - apps/api/app/api/v1/commitments.py        (/commitments*)
 *   - apps/api/app/api/v1/learning_artifacts.py (/learning-artifacts*)
 */
import api from './api';

const commitmentService = {
  /** GET /commitments/open — open/live commitments, optionally session-scoped. */
  listOpen(sessionId) {
    const params = {};
    if (sessionId) params.session_id = sessionId;
    return api.get('/commitments/open', { params });
  },

  /**
   * GET /commitments/red-flags — drift scan over open commitments.
   * Killswitch-gated server-side: returns [] if the engine is disabled.
   */
  listRedFlags({ minLevel = 'warn', sessionId } = {}) {
    const params = { min_level: minLevel };
    if (sessionId) params.session_id = sessionId;
    return api.get('/commitments/red-flags', { params });
  },

  /**
   * POST /commitments/{id}/complete — proof-gated completion. The server
   * returns 409 unless proof_refs are supplied or the user confirms now.
   */
  complete(commitmentId, { proofRefs = [], userConfirmed = false } = {}) {
    return api.post(`/commitments/${commitmentId}/complete`, {
      proof_refs: proofRefs,
      user_confirmed: userConfirmed,
    });
  },

  /** GET /learning-artifacts — recent distilled learning artifacts. */
  listLearningArtifacts({ limit = 50 } = {}) {
    return api.get('/learning-artifacts', { params: { limit } });
  },

  /** GET /learning-artifacts/failed-assumptions — de-duplicated failed assumptions. */
  listFailedAssumptions({ limit = 50 } = {}) {
    return api.get('/learning-artifacts/failed-assumptions', { params: { limit } });
  },
};

export default commitmentService;
