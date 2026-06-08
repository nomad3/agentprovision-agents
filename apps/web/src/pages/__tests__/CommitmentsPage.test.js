import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CommitmentsPage from '../CommitmentsPage';

jest.mock('../../services/commitments', () => ({
  __esModule: true,
  default: {
    listOpen: jest.fn(),
    listRedFlags: jest.fn(),
    listLearningArtifacts: jest.fn(),
    listFailedAssumptions: jest.fn(),
    complete: jest.fn(),
  },
}));
jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('../../components/common', () => ({
  __esModule: true,
  EmptyState: ({ title, description }) => (
    <div data-testid="empty-state"><div>{title}</div><div>{description}</div></div>
  ),
  LoadingSpinner: ({ text }) => <div role="status">{text}</div>,
  useToast: () => mockToast,
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, fallback) => fallback || key }),
}));

const commitmentService = require('../../services/commitments').default;

const openCommitments = [
  {
    id: 'c-1',
    title: 'Ship the accountable-learning operator surface',
    state: 'in_progress',
    owner_agent_slug: 'luna',
    proof_required: ['merged_pr_url'],
    proof_refs: [],
    risk_threshold: 'medium',
    due_at: null,
    checkpoint_at: null,
  },
  {
    id: 'c-2',
    title: 'Confirm migration 163 applied',
    state: 'open',
    owner_agent_slug: 'luna',
    proof_required: [],
    proof_refs: ['migration_log'],
    risk_threshold: null,
    due_at: null,
    checkpoint_at: null,
  },
];

const redFlags = [
  {
    commitment_id: 'c-1',
    level: 'escalate',
    risk: 'Checkpoint overdue with no proof attached',
    evidence: 'checkpoint_at 2026-06-06, now 2026-06-07, proof_refs empty',
    missing: ['merged_pr_url'],
    decision_needed: 'Renegotiate the deadline or attach proof now',
    recommended_next_action: 'Attach the merged PR url or move the checkpoint',
    triggers: ['overdue_checkpoint', 'missing_proof'],
  },
];

const artifacts = [
  {
    artifact_id: 'a-1',
    task_summary: 'Built operator surface; mis-scoped the red-flag killswitch first',
    outcome_quality: 'partially_succeeded',
    memory_write_recommendation: 'failed_assumption',
    failed_assumptions: ['assumed red-flag engine on by default'],
    confidence: 'high',
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <CommitmentsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  commitmentService.listOpen.mockResolvedValue({ data: openCommitments });
  commitmentService.listRedFlags.mockResolvedValue({ data: redFlags });
  commitmentService.listLearningArtifacts.mockResolvedValue({ data: artifacts });
  commitmentService.listFailedAssumptions.mockResolvedValue({ data: { failed_assumptions: [] } });
  commitmentService.complete.mockResolvedValue({ data: { state: 'fulfilled' } });
});

describe('CommitmentsPage', () => {
  test('loads open commitments and renders typed status', async () => {
    renderPage();
    await waitFor(() => expect(commitmentService.listOpen).toHaveBeenCalled());
    // The title can surface in both the at-risk card and the open list.
    const titles = await screen.findAllByText('Ship the accountable-learning operator surface');
    expect(titles.length).toBeGreaterThan(0);
    // typed status surfaced (plan §12: same small statuses across surfaces)
    expect(screen.getByText('in_progress')).toBeInTheDocument();
  });

  test('flags proof-missing commitments distinctly', async () => {
    renderPage();
    // c-1 requires proof but has none → proof missing
    expect(await screen.findByTestId('proof-missing-c-1')).toBeInTheDocument();
    // c-2 has proof → not proof missing
    expect(screen.queryByTestId('proof-missing-c-2')).not.toBeInTheDocument();
  });

  test('renders red flags and lets the user inspect why one was raised', async () => {
    renderPage();
    await screen.findByTestId('inspect-redflag-c-1');
    // red-flag level badge
    expect(screen.getByText('escalate')).toBeInTheDocument();
    // the decision/reason is revealed on demand, not before
    expect(screen.queryByText(/Renegotiate the deadline or attach proof now/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('inspect-redflag-c-1'));
    expect(await screen.findByText(/Renegotiate the deadline or attach proof now/)).toBeInTheDocument();
  });

  test('renders recent learning artifacts with outcome quality', async () => {
    renderPage();
    await screen.findByText(/Built operator surface/);
    expect(screen.getByText('partially_succeeded')).toBeInTheDocument();
  });

  test('shows empty state when there are no open commitments', async () => {
    commitmentService.listOpen.mockResolvedValue({ data: [] });
    commitmentService.listRedFlags.mockResolvedValue({ data: [] });
    commitmentService.listLearningArtifacts.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument();
  });
});
