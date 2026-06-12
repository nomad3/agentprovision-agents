import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import VetPracticeDashboardPage from '../VetPracticeDashboardPage';

jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const api = require('../../services/api').default;

const dashboard = {
  practice_name: 'The Animal Doctor SOC',
  summary: {
    agents_present: 10,
    agents_expected: 10,
    storage_connected: 1,
    storage_expected: 2,
    flows_ready: 3,
    flows_expected: 9,
    workflows_installed: 8,
    workflows_expected: 8,
  },
  launch_context: {
    lead_clinicians: [
      { name: 'Dr. Angelo Castillo', focus: 'The Animal Doctor SOC multi-location GP practice' },
      { name: 'Dr. Brett', focus: 'Cardiology referral and report loop' },
    ],
    locations: ['Anaheim', 'Buena Park', 'Mission Viejo'],
    mvp_sources: ['Google Drive practice packets', 'OneDrive practice packets'],
    initial_meetings: [
      {
        title: 'Angelo practice-management kickoff',
        summary: 'Confirmed file-first MVP and three-location daily operations support.',
      },
      {
        title: 'Brett cardiology beachhead',
        summary: 'Defined the referral package loop.',
      },
    ],
  },
  flows: [
    {
      key: 'pet_health_concierge',
      name: '24/7 Pet Health Concierge',
      description: 'Owner message intake with staff handoff file.',
      primary_agent: 'Pet Health Concierge Agent',
      primary_agent_id: 'agent-1',
      workflow_template: 'Vet File Intake Packet',
      workflow: { id: 'wf-1', installed: true },
      ready: true,
      agent_present: true,
      approval_required: true,
      sample_queue: [
        {
          id: 'ang-001',
          title: 'Milo - limping after dog park',
          source: 'Owner web request',
          location: 'Anaheim',
          priority: 'same-day review',
          status: 'Needs packet',
          next_step: 'Confirm patient identity and save intake packet.',
        },
      ],
      packet_checklist: ['Owner and pet identifiers', 'Urgency and red flags'],
      workflow_steps: [
        { index: 1, id: 'draft', type: 'agent', agent: 'Front Desk Agent' },
        { index: 2, id: 'save', type: 'mcp_tool', destination: 'Google Drive' },
      ],
      review_gate: {
        label: 'Staff review before owner guidance',
        reviewer: 'Front desk or clinical team',
        reason: 'Staff decide scheduling and medical guidance.',
        enforced_by_workflow: false,
      },
    },
    {
      key: 'soap_note_sync',
      name: 'SOAP note draft packet',
      description: 'Transcript to SOAP draft.',
      primary_agent: 'SOAP Note Agent',
      primary_agent_id: 'agent-2',
      workflow_template: 'Vet SOAP Draft Packet',
      workflow: { id: 'wf-2', installed: true },
      ready: true,
      agent_present: true,
      approval_required: true,
      sample_queue: [
        {
          id: 'ang-005',
          title: 'Charlie - wellness visit transcript',
          source: 'Scribe transcript upload',
          location: 'Buena Park',
          priority: 'DVM review',
          status: 'Needs SOAP draft',
          next_step: 'Convert transcript into SOAP sections.',
        },
      ],
      packet_checklist: ['Subjective', 'Objective', 'Assessment', 'Plan'],
      workflow_steps: [
        { index: 1, id: 'draft_soap', type: 'agent', agent: 'SOAP Note Agent' },
        { index: 2, id: 'approval', type: 'human_approval', name: 'DVM review required' },
      ],
      review_gate: {
        label: 'DVM approval required',
        reviewer: 'Dr. Angelo or attending DVM',
        reason: 'Clinical documentation is drafted by the agent and signed by licensed staff.',
        enforced_by_workflow: true,
      },
    },
  ],
  specialist_lanes: [
    {
      key: 'cardiac_referral_loop',
      name: 'Cardiac referral loop',
      description: 'Referral package to DACVIM draft.',
      lead_clinician: 'Dr. Brett',
      sample_queue: [
        {
          id: 'brett-001',
          title: 'Bailey - echo referral package',
          next_step: 'Extract echo measurements and hold for Dr. Brett approval.',
        },
      ],
    },
  ],
  storage: [
    { integration_name: 'google_drive', display_name: 'Google Drive', connected: true, configured: true, account_email: 'ops@example.com' },
    { integration_name: 'onedrive', display_name: 'OneDrive', connected: false, configured: true },
  ],
  agents: [
    { name: 'Pet Health Concierge Agent', description: 'Owner-facing concierge.', status: 'production' },
  ],
  future_practice_systems: [
    { key: 'covetrus_pulse', name: 'Practice management system', note: 'Future integration.', status: 'future' },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <VetPracticeDashboardPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  api.get.mockResolvedValue({ data: dashboard });
});

describe('VetPracticeDashboardPage', () => {
  test('renders the launch brief, daily queue, and specialist lane', async () => {
    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/vet-practice/dashboard',
      { params: { variant: 'gp_full' } },
    ));
    expect(await screen.findByText('Dr. Angelo Castillo')).toBeInTheDocument();
    expect(screen.getByText('Angelo practice-management kickoff')).toBeInTheDocument();
    expect(screen.getByText('Milo - limping after dog park')).toBeInTheDocument();
    expect(screen.getByText('Bailey - echo referral package')).toBeInTheDocument();
    expect(screen.getByText('Practice Software Prep')).toBeInTheDocument();
  });

  test('switches rooms and opens the selected workflow builder', async () => {
    renderPage();
    await screen.findByText('Milo - limping after dog park');

    fireEvent.click(screen.getByRole('tab', { name: /SOAP note draft packet/i }));
    expect(screen.getByText('Charlie - wellness visit transcript')).toBeInTheDocument();
    expect(screen.getByText('DVM review required')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Open Process/i }));
    expect(mockNavigate).toHaveBeenCalledWith('/workflows/builder/wf-2');
  });
});
