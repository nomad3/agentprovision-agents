import { render, screen, waitFor } from '@testing-library/react';
import WorkspacePage from '../WorkspacePage';
import VetPracticeAliasPage from '../VetPracticeAliasPage';

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

const mockNavigate = jest.fn();
let mockSlug = 'vet-practice';
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ slug: mockSlug }),
    Navigate: ({ to }) => <div data-testid="navigate" data-to={to}>redirected workspace</div>,
  };
});

jest.mock('../../services/workspaces', () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    list: jest.fn(),
  },
}));

const workspaceService = require('../../services/workspaces').default;

const sampleDetail = {
  descriptor: {
    slug: 'vet-practice',
    label: 'Vet Practice',
    description: 'File-first operating workspace for veterinary practice management.',
    route: '/workspaces/vet-practice',
    widgets: [
      { key: 'launch_brief', title: 'Launch Brief', type: 'launch_brief', span: 2 },
      { key: 'daily_work_queue', title: 'Daily Work Queue', type: 'work_queue', span: 2 },
      { key: 'source_packets', title: 'Source Packets', type: 'source_packets', span: 2 },
      { key: 'system_readiness', title: 'Practice Software Prep', type: 'system_readiness', span: 1 },
    ],
  },
  layout: [],
  widgets: [
    {
      key: 'launch_brief',
      state: 'ready',
      example: true,
      setup_blockers: [],
      data: {
        practice_name: 'The Animal Doctor SOC',
        launch_context: {
          lead_clinicians: [
            { name: 'Dr. Angelo Castillo', focus: 'The Animal Doctor SOC multi-location GP practice' },
            { name: 'Dr. Brett', focus: 'Cardiology referral and report loop' },
          ],
          locations: ['Anaheim', 'Buena Park'],
          mvp_sources: ['Google Drive practice packets', 'OneDrive practice packets'],
          initial_meetings: [
            { title: 'Angelo practice-management kickoff', summary: 'Confirmed file-first MVP.' },
          ],
        },
      },
    },
    {
      key: 'source_packets',
      state: 'ready',
      example: false,
      setup_blockers: [],
      data: {
        sources: [
          {
            provider: 'google_drive',
            label: 'Brett',
            folder_id: 'drive-folder-1',
            folder_name: 'Brett',
            account_email: 'vet@example.com',
            state: 'ready',
            counts: { files: 4, pdfs: 4 },
            files: [
              { id: 'f1', name: 'Winnie Nieto.pdf', kind: 'pdf' },
              { id: 'f2', name: 'Invoice WMAH 2-14-26.pdf', kind: 'pdf' },
            ],
          },
        ],
      },
    },
    {
      key: 'daily_work_queue',
      state: 'setup_required',
      example: true,
      setup_blockers: ['Connect Google Drive or OneDrive before claiming file packet automation is live.'],
      data: {
        items: [
          {
            id: 'ang-001',
            flow_key: 'pet_health_concierge',
            flow_name: 'Pet Health Concierge',
            title: 'Milo - limping after dog park',
            next_step: 'Confirm patient identity and save intake packet.',
            location: 'Anaheim',
            priority: 'same-day review',
            status: 'Needs packet',
          },
        ],
      },
    },
    {
      key: 'system_readiness',
      state: 'setup_required',
      example: false,
      setup_blockers: ['Connect Google Drive or OneDrive before claiming file packet automation is live.'],
      data: {
        storage: [
          { integration_name: 'google_drive', display_name: 'Google Drive', connected: false },
        ],
        practice_systems: [
          { key: 'covetrus_pulse', name: 'Practice management system', note: 'Future readiness item.', status: 'future' },
        ],
      },
    },
  ],
};

function renderWorkspace() {
  return render(<WorkspacePage />);
}

describe('WorkspacePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSlug = 'vet-practice';
    workspaceService.get.mockResolvedValue({ data: sampleDetail });
  });

  test('renders the vet workspace through generic widget payloads', async () => {
    renderWorkspace();

    expect(await screen.findByText('Vet Practice')).toBeInTheDocument();
    expect(screen.getByText('Dr. Angelo Castillo')).toBeInTheDocument();
    expect(screen.getByText('Dr. Brett')).toBeInTheDocument();
    expect(screen.getByText('Milo - limping after dog park')).toBeInTheDocument();
    expect(screen.getByText('Source Packets')).toBeInTheDocument();
    expect(screen.getByText('Winnie Nieto.pdf')).toBeInTheDocument();
    expect(screen.getByText('Practice Software Prep')).toBeInTheDocument();
    expect(screen.getAllByText('Example preview').length).toBeGreaterThan(0);
    expect(screen.queryByText(/MCP Tool/i)).not.toBeInTheDocument();
  });

  test('shows setup blockers instead of live capability claims', async () => {
    renderWorkspace();

    expect((await screen.findAllByText(/Connect Google Drive or OneDrive/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Needs setup').length).toBeGreaterThan(0);
  });

  test('clears stale workspace detail when a new slug fails to load', async () => {
    const { rerender } = renderWorkspace();
    expect(await screen.findByText('Milo - limping after dog park')).toBeInTheDocument();

    workspaceService.get.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Workspace not found' } } });
    mockSlug = 'sales-crm';
    rerender(<WorkspacePage />);

    expect(await screen.findByText(/Workspace not found/)).toBeInTheDocument();
    expect(screen.queryByText('Milo - limping after dog park')).not.toBeInTheDocument();
  });
});

describe('VetPracticeAliasPage', () => {
  test('checks installation before redirecting the legacy /practice route', async () => {
    workspaceService.get.mockResolvedValue({ data: sampleDetail });

    render(<VetPracticeAliasPage />);

    await waitFor(() => {
      expect(workspaceService.get).toHaveBeenCalledWith('vet-practice');
    });
    expect(await screen.findByTestId('navigate')).toHaveAttribute('data-to', '/workspaces/vet-practice');
  });
});
