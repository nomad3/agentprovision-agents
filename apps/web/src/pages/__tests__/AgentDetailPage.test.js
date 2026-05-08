import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentDetailPage from '../AgentDetailPage';

jest.mock('../../services/agent', () => ({
  __esModule: true,
  default: {
    getById: jest.fn(),
    getAll: jest.fn(),
    getTasks: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
  },
}));
jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../../components/agent/TestsTabSection', () => () => (
  <div data-testid="tests-tab" />
));

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ id: 'agent-1' }),
  };
});

const agentService = require('../../services/agent').default;

const sampleAgent = {
  id: 'agent-1',
  name: 'Cardiac Analyst',
  description: 'DACVIM cardiac evaluator',
  status: 'production',
  role: 'analyst',
  autonomy_level: 'supervised',
  default_model_tier: 'full',
  config: {
    system_prompt: 'You are a cardiologist',
    skills: ['report_generation', 'knowledge_search'],
    temperature: 0.2,
    max_tokens: 2000,
  },
  tool_groups: ['data', 'reports'],
  capabilities: ['cardiac_eval'],
};

const originalFetch = global.fetch;

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentDetailPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  agentService.getById.mockResolvedValue({ data: sampleAgent });
  agentService.getAll.mockResolvedValue({ data: [sampleAgent] });
  agentService.getTasks.mockResolvedValue({ data: [] });
  agentService.update.mockResolvedValue({ data: sampleAgent });
  agentService.delete.mockResolvedValue({});
  global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }));
  // Stub localStorage for the auth token read.
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: jest.fn(() => 'tok-test'),
      setItem: jest.fn(),
      removeItem: jest.fn(),
    },
    configurable: true,
  });
});

afterAll(() => {
  global.fetch = originalFetch;
});

describe('AgentDetailPage', () => {
  test('loads the agent on mount and renders the header', async () => {
    renderPage();
    await waitFor(() => expect(agentService.getById).toHaveBeenCalledWith('agent-1'));
    expect(await screen.findByText('Cardiac Analyst')).toBeInTheDocument();
    expect(screen.getByText('DACVIM cardiac evaluator')).toBeInTheDocument();
  });

  test('renders all tab nav items', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    const expectedTabs = [
      'overview', 'relations', 'tasks', 'config',
      'performance', 'audit', 'versions', 'integrations', 'tests',
    ];
    expectedTabs.forEach(tab => {
      // Tab labels are capitalized via CSS — text is the lowercase value.
      expect(screen.getByText(tab)).toBeInTheDocument();
    });
  });

  test('Overview tab is active by default', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    // Overview shows stat cards labelled "Total Tasks" / "Success Rate"
    expect(screen.getByText('Total Tasks')).toBeInTheDocument();
    expect(screen.getByText('Success Rate')).toBeInTheDocument();
  });

  test('switching to Performance tab triggers /performance fetch', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('performance'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/agents/agent-1/performance'),
        expect.any(Object),
      );
    });
  });

  test('switching to Audit tab triggers /audit-log fetch', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('audit'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/agents/agent-1/audit-log'),
        expect.any(Object),
      );
    });
  });

  test('switching to Versions tab triggers /versions fetch', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('versions'));
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/agents/agent-1/versions'),
        expect.any(Object),
      );
    });
  });

  test('Versions tab renders rollback buttons for non-current versions', async () => {
    global.fetch = jest.fn((url) => {
      if (url.includes('/versions') && !url.includes('rollback')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve([
              { id: 'v-1', version: 3, is_current: true, status: 'production', promoted_at: '2026-05-01T00:00:00Z' },
              { id: 'v-2', version: 2, is_current: false, status: 'archived', promoted_at: '2026-04-15T00:00:00Z' },
            ]),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('versions'));
    expect(await screen.findByText('Rollback to this version')).toBeInTheDocument();
    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getByText('v3')).toBeInTheDocument();
    expect(screen.getByText('v2')).toBeInTheDocument();
  });

  test('clicking Rollback POSTs to /versions/{n}/rollback', async () => {
    global.fetch = jest.fn((url, opts) => {
      if (url.includes('/versions') && !url.includes('rollback')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve([
              { id: 'v-1', version: 3, is_current: true, status: 'production' },
              { id: 'v-2', version: 2, is_current: false, status: 'archived' },
            ]),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('versions'));
    const rollback = await screen.findByText('Rollback to this version');
    fireEvent.click(rollback);
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/agents/agent-1/versions/2/rollback'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  test('switching to Integrations tab triggers fetches', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('integrations'));
    await waitFor(() => {
      // Either /integrations or related fetch is triggered
      const calls = global.fetch.mock.calls.map(c => c[0]);
      expect(calls.some(u => u.includes('/integrations'))).toBe(true);
    });
  });

  test('Tests tab renders the TestsTabSection child', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByText('tests'));
    expect(await screen.findByTestId('tests-tab')).toBeInTheDocument();
  });

  test('Delete button opens the confirmation modal', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    // Modal opens — confirm button text is "Delete"
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });

  test('does not render the agent header until the load resolves', async () => {
    let resolveAgent;
    agentService.getById.mockImplementation(
      () => new Promise(res => { resolveAgent = res; }),
    );
    renderPage();
    // Before resolution, the Cardiac Analyst header should not be in the
    // DOM (we're still in the loading branch).
    expect(screen.queryByText('Cardiac Analyst')).not.toBeInTheDocument();
    resolveAgent({ data: sampleAgent });
    await waitFor(() => expect(screen.getByText('Cardiac Analyst')).toBeInTheDocument());
  });
});
