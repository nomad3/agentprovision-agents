import commitmentService from '../commitments';
import api from '../api';

jest.mock('../api');

describe('commitmentService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: [] });
    api.post.mockResolvedValue({ data: {} });
  });

  test('listOpen hits /commitments/open with optional session scope', async () => {
    await commitmentService.listOpen();
    expect(api.get).toHaveBeenCalledWith('/commitments/open', { params: {} });

    await commitmentService.listOpen('sess-1');
    expect(api.get).toHaveBeenCalledWith('/commitments/open', { params: { session_id: 'sess-1' } });
  });

  test('listRedFlags hits /commitments/red-flags with min_level default warn', async () => {
    await commitmentService.listRedFlags();
    expect(api.get).toHaveBeenCalledWith('/commitments/red-flags', { params: { min_level: 'warn' } });

    await commitmentService.listRedFlags({ minLevel: 'escalate', sessionId: 's2' });
    expect(api.get).toHaveBeenCalledWith('/commitments/red-flags', {
      params: { min_level: 'escalate', session_id: 's2' },
    });
  });

  test('complete posts proof refs / user confirmation to the proof gate', async () => {
    await commitmentService.complete('c-1', { proofRefs: ['pr#828'], userConfirmed: false });
    expect(api.post).toHaveBeenCalledWith('/commitments/c-1/complete', {
      proof_refs: ['pr#828'],
      user_confirmed: false,
    });

    await commitmentService.complete('c-2', {});
    expect(api.post).toHaveBeenCalledWith('/commitments/c-2/complete', {
      proof_refs: [],
      user_confirmed: false,
    });
  });

  test('listLearningArtifacts + listFailedAssumptions read the learning surface', async () => {
    await commitmentService.listLearningArtifacts();
    expect(api.get).toHaveBeenCalledWith('/learning-artifacts', { params: { limit: 50 } });

    await commitmentService.listFailedAssumptions();
    expect(api.get).toHaveBeenCalledWith('/learning-artifacts/failed-assumptions', { params: { limit: 50 } });
  });
});
