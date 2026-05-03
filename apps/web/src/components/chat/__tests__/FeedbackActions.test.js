import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import FeedbackActions from '../FeedbackActions';
import learningService from '../../../services/learningService';

jest.mock('../../../services/learningService', () => ({
  __esModule: true,
  default: { submitFeedback: jest.fn() },
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k, fallback) => fallback || k }),
}));

describe('FeedbackActions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    learningService.submitFeedback.mockResolvedValue({ ok: true });
  });

  test('renders thumbs and flag dropdown', () => {
    render(<FeedbackActions trajectoryId="t1" stepIndex={0} />);
    expect(screen.getByTitle('Helpful')).toBeInTheDocument();
    expect(screen.getByTitle('Not helpful')).toBeInTheDocument();
  });

  test('thumbs up posts a feedback record and renders the receipt', async () => {
    render(<FeedbackActions trajectoryId="t1" stepIndex={2} />);
    fireEvent.click(screen.getByTitle('Helpful'));
    await waitFor(() => {
      expect(learningService.submitFeedback).toHaveBeenCalledWith({
        trajectory_id: 't1',
        step_index: 2,
        feedback_type: 'thumbs_up',
      });
    });
    expect(await screen.findByText(/Submitted/)).toBeInTheDocument();
  });

  test('thumbs down posts thumbs_down feedback', async () => {
    render(<FeedbackActions trajectoryId="t1" stepIndex={0} />);
    fireEvent.click(screen.getByTitle('Not helpful'));
    await waitFor(() => {
      expect(learningService.submitFeedback).toHaveBeenCalledWith(
        expect.objectContaining({ feedback_type: 'thumbs_down' })
      );
    });
  });

  test('hides controls after a feedback is submitted', async () => {
    render(<FeedbackActions trajectoryId="t1" stepIndex={0} />);
    fireEvent.click(screen.getByTitle('Helpful'));
    await screen.findByText(/Submitted/);
    expect(screen.queryByTitle('Helpful')).not.toBeInTheDocument();
  });
});
