import learningService from '../learningService';
import api from '../api';

jest.mock('../api');

describe('learningService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: { ok: true } });
    api.post.mockResolvedValue({ data: { ok: true } });
    api.put.mockResolvedValue({ data: { ok: true } });
  });

  test('overview, experiences, trajectory endpoints', async () => {
    await learningService.getOverview();
    expect(api.get).toHaveBeenCalledWith('/rl/overview');

    await learningService.getExperiences({ decision_point: 'chat_response' });
    expect(api.get).toHaveBeenCalledWith('/rl/experiences', { params: { decision_point: 'chat_response' } });

    await learningService.getTrajectory('t1');
    expect(api.get).toHaveBeenCalledWith('/rl/experiences/t1');
  });

  test('feedback + decision-points', async () => {
    await learningService.submitFeedback({ trajectory_id: 't1', feedback_type: 'thumbs_up' });
    expect(api.post).toHaveBeenCalledWith('/rl/feedback', { trajectory_id: 't1', feedback_type: 'thumbs_up' });

    await learningService.getDecisionPoints();
    expect(api.get).toHaveBeenCalledWith('/rl/decision-points');

    await learningService.getDecisionPoint('chat_response');
    expect(api.get).toHaveBeenCalledWith('/rl/decision-points/chat_response');
  });

  test('experiments + reviews', async () => {
    await learningService.getExperiments();
    expect(api.get).toHaveBeenCalledWith('/rl/experiments');

    await learningService.triggerExperiment('chat_response');
    expect(api.post).toHaveBeenCalledWith('/rl/experiments/trigger?decision_point=chat_response');

    await learningService.getPendingReviews({ limit: 5 });
    expect(api.get).toHaveBeenCalledWith('/rl/reviews/pending', { params: { limit: 5 } });

    await learningService.rateExperience('e1', 4);
    expect(api.post).toHaveBeenCalledWith('/rl/reviews/e1/rate?rating=4');

    await learningService.batchRate([{ id: 'a', rating: 5 }]);
    expect(api.post).toHaveBeenCalledWith('/rl/reviews/batch-rate', [{ id: 'a', rating: 5 }]);
  });

  test('settings + policy', async () => {
    await learningService.getSettings();
    expect(api.get).toHaveBeenCalledWith('/rl/settings');

    await learningService.updateSettings({ exploration_rate: 0.05 });
    expect(api.put).toHaveBeenCalledWith('/rl/settings', { exploration_rate: 0.05 });

    await learningService.getPolicyVersions();
    expect(api.get).toHaveBeenCalledWith('/rl/policy/versions');

    await learningService.rollbackPolicy('chat_response', 3);
    expect(api.post).toHaveBeenCalledWith('/rl/policy/rollback?decision_point=chat_response&version=3');
  });

  test('platform performance + export', async () => {
    await learningService.getPlatformPerformance();
    expect(api.get).toHaveBeenCalledWith('/rl/platform-performance', { params: { min_experiences: 3 } });

    await learningService.getPlatformPerformance(10);
    expect(api.get).toHaveBeenCalledWith('/rl/platform-performance', { params: { min_experiences: 10 } });

    await learningService.exportExperiences('chat_response');
    expect(api.get).toHaveBeenCalledWith('/rl/export', expect.objectContaining({
      params: { decision_point: 'chat_response' },
      responseType: 'blob',
    }));
  });
});
