import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentsPage from '../AgentsPage';

// ── Boundary mocks ────────────────────────────────────────────────────
// Service modules are tested in Phase 2; mock them at the boundary.
jest.mock('../../services/agent', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(),
    getTasks: jest.fn(),
    delete: jest.fn(),
  },
}));
jest.mock('../../services/api', () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

// Layout pulls in many context providers we don't need to test the page
// surface, so we render its children directly.
jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

// MarketplaceSection makes its own API calls — out of scope for AgentsPage tests.
jest.mock('../../components/agent/MarketplaceSection', () => () => (
  <div data-testid="marketplace-section">marketplace</div>
));

// HireAgentWizard is rendered inside the Hire modal; its internals are
// covered separately. Render a stub that exposes the close handler.
jest.mock('../../components/HireAgentWizard', () => ({ onClose }) => (
  <div data-testid="hire-wizard">
    <button type="button" onClick={onClose}>close-wizard</button>
  </div>
));

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// i18n: just return the key/default value so we can assert against
// human-readable copy.
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      // Support default-value form: t('key', 'Default')
      if (typeof opts === 'string') return opts;
      // Support interpolation: t('key', { name })
      if (opts && typeof opts === 'object' && opts.name) return `${key}: ${opts.name}`;
      return key;
    },
  }),
}));

const agentService = require('../../services/agent').default;
const api = require('../../services/api').default;

const sampleAgents = [
  {
    id: 'a-1',
    name: 'Luna Supervisor',
    description: 'Personal assistant orchestrator',
    status: 'production',
    role: 'supervisor',
    autonomy_level: 'supervised',
    default_model_tier: 'full',
    owner_user_id: 'u-1',
    config: { skills: ['sql_query', 'knowledge_search'] },
    skills: [],
  },
  {
    id: 'a-2',
    name: 'Cardiac Analyst',
    description: 'DACVIM cardiac evaluator',
    status: 'draft',
    role: 'analyst',
    autonomy_level: 'approval_required',
    default_model_tier: 'light',
    owner_user_id: null,
    config: {},
    skills: [{ skill_name: 'report_generation' }],
  },
];

const sampleExternal = [
  {
    id: 'ext-1',
    name: 'Acme Sales Bot',
    description: 'Copilot Studio agent',
    status: 'online',
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  agentService.getAll.mockResolvedValue({ data: sampleAgents });
  agentService.getTasks.mockResolvedValue({ data: [] });
  agentService.delete.mockResolvedValue({});
  api.get.mockImplementation((url) => {
    if (url === '/external-agents') return Promise.resolve({ data: sampleExternal });
    return Promise.resolve({ data: [] });
  });
  api.post.mockResolvedValue({ data: {} });
  api.delete.mockResolvedValue({});
});

describe('AgentsPage', () => {
  test('loads agents + external agents on mount and renders the fleet header', async () => {
    renderPage();
    await waitFor(() => expect(agentService.getAll).toHaveBeenCalled());
    expect(api.get).toHaveBeenCalledWith('/external-agents');
    expect(agentService.getTasks).toHaveBeenCalled();
    expect(await screen.findByText('Luna Supervisor')).toBeInTheDocument();
    expect(screen.getByText('Cardiac Analyst')).toBeInTheDocument();
    // Fleet subtitle counts
    expect(screen.getByText(/2 agents/)).toBeInTheDocument();
  });

  test('renders status badges for each lifecycle state', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    // Status text comes through agent.status
    expect(screen.getByText('production')).toBeInTheDocument();
    expect(screen.getByText('draft')).toBeInTheDocument();
  });

  test('search filter narrows the visible agents', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    const search = screen.getByPlaceholderText('searchPlaceholder');
    fireEvent.change(search, { target: { value: 'cardiac' } });
    expect(screen.queryByText('Luna Supervisor')).not.toBeInTheDocument();
    expect(screen.getByText('Cardiac Analyst')).toBeInTheDocument();
  });

  test('lifecycle filter chips restrict by status', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.click(screen.getByRole('button', { name: 'Draft' }));
    expect(screen.queryByText('Luna Supervisor')).not.toBeInTheDocument();
    expect(screen.getByText('Cardiac Analyst')).toBeInTheDocument();
  });

  test('shows empty state when no agents match the search', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.change(screen.getByPlaceholderText('searchPlaceholder'), {
      target: { value: 'definitely-not-an-agent-here' },
    });
    expect(screen.getByText('noAgentsMatch')).toBeInTheDocument();
    expect(screen.getByText('tryDifferent')).toBeInTheDocument();
  });

  test('shows no-agents-yet state when api returns an empty list', async () => {
    agentService.getAll.mockResolvedValue({ data: [] });
    api.get.mockResolvedValue({ data: [] });
    renderPage();
    await waitFor(() => expect(screen.getByText('noAgentsYet')).toBeInTheDocument());
    expect(screen.getByText('createFirst')).toBeInTheDocument();
  });

  test('opens the Import Agent modal and submits on click', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.click(screen.getByRole('button', { name: /Import Agent/i }));
    // Modal textarea is the only one inside the open dialog.
    const dialog = await screen.findByRole('dialog');
    const textarea = within(dialog).getByRole('textbox');
    fireEvent.change(textarea, { target: { value: 'name: My Agent\ndescription: test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/agents/import', {
        content: 'name: My Agent\ndescription: test',
      });
    });
  });

  test('Import button is disabled when content is empty', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.click(screen.getByRole('button', { name: /Import Agent/i }));
    const dialog = await screen.findByRole('dialog');
    const importBtn = within(dialog).getByRole('button', { name: 'Import' });
    expect(importBtn).toBeDisabled();
  });

  test('opens the Hire External Agent wizard modal', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.click(screen.getByRole('button', { name: /Hire External Agent/i }));
    expect(await screen.findByTestId('hire-wizard')).toBeInTheDocument();
  });

  test('Agent Wizard button navigates to /agents/wizard', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    fireEvent.click(screen.getByRole('button', { name: /agentWizard/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/agents/wizard');
  });

  test('clicking an agent card navigates to its detail page', async () => {
    renderPage();
    const card = await screen.findByText('Luna Supervisor');
    fireEvent.click(card.closest('article'));
    expect(mockNavigate).toHaveBeenCalledWith('/agents/a-1');
  });

  test('Promote button calls the promote endpoint for draft agents', async () => {
    renderPage();
    await screen.findByText('Cardiac Analyst');
    // Cardiac Analyst is draft → has a Promote button
    const promote = screen.getByRole('button', { name: 'Promote' });
    fireEvent.click(promote);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/agents/a-2/promote');
    });
  });

  test('Deprecate button calls the deprecate endpoint for production agents', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    const deprecate = screen.getByRole('button', { name: 'Deprecate' });
    fireEvent.click(deprecate);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/agents/a-1/deprecate');
    });
  });

  test('Delete flow opens the confirm modal and calls the service on confirm', async () => {
    renderPage();
    await screen.findByText('Luna Supervisor');
    const deleteBtns = screen.getAllByRole('button', { name: 'Delete' });
    // Card-footer Delete button (first match).
    fireEvent.click(deleteBtns[0]);
    // Modal opens with confirmation — find inside dialog.
    const dialog = await screen.findByRole('dialog');
    const confirmDelete = within(dialog).getByRole('button', { name: /deleteModal\.delete/i });
    fireEvent.click(confirmDelete);
    await waitFor(() => expect(agentService.delete).toHaveBeenCalledWith('a-1'));
  });

  test('renders external agents section with online status', async () => {
    renderPage();
    expect(await screen.findByText('Acme Sales Bot')).toBeInTheDocument();
    // External agents subtitle counts via header
    expect(screen.getByText(/1 external/)).toBeInTheDocument();
  });

  test('shows error alert if loading agents fails', async () => {
    agentService.getAll.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    expect(await screen.findByText('errors.load')).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
