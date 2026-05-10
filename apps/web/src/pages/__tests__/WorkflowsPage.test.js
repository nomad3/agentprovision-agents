import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import WorkflowsPage from '../WorkflowsPage';

// ── Boundary mocks ────────────────────────────────────────────────────
jest.mock('../../services/taskService', () => ({
  __esModule: true,
  default: {
    listWorkflows: jest.fn(),
    getWorkflowStats: jest.fn(),
    getTrace: jest.fn(),
    getWorkflowHistory: jest.fn(),
    approve: jest.fn(),
    reject: jest.fn(),
  },
}));

jest.mock('../../services/dynamicWorkflowService', () => ({
  __esModule: true,
  default: {
    list: jest.fn(),
    get: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
    activate: jest.fn(),
    pause: jest.fn(),
    run: jest.fn(),
    listRuns: jest.fn(),
    getRun: jest.fn(),
    dryRun: jest.fn(),
    getIntegrationStatus: jest.fn(),
    getToolMapping: jest.fn(),
    browseTemplates: jest.fn(),
    installTemplate: jest.fn(),
  },
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../../components/TaskTimeline', () => () => (
  <div data-testid="task-timeline" />
));

// Stub the heavy tab components — they own their own service calls and
// have their own tests in the workflows/__tests__ tree (out of scope).
jest.mock('../../components/workflows/DynamicWorkflowsTab', () => () => (
  <div data-testid="dynamic-workflows-tab">dynamic-workflows-tab</div>
));
jest.mock('../../components/workflows/TemplatesTab', () => () => (
  <div data-testid="templates-tab">templates-tab</div>
));
jest.mock('../../components/workflows/RunsTab', () => () => (
  <div data-testid="runs-tab">runs-tab</div>
));

// Drive the active tab via the search params mock — tests can mutate
// global state to force a tab without clicking through the chip row.
// Stash on globalThis to keep the jest.mock factory hoist-safe.
globalThis.__wfParams = new URLSearchParams();
globalThis.__wfSetParams = jest.fn((updater) => {
  if (typeof updater === 'function') {
    globalThis.__wfParams = updater(globalThis.__wfParams);
  } else if (updater instanceof URLSearchParams) {
    globalThis.__wfParams = updater;
  } else {
    globalThis.__wfParams = new URLSearchParams(updater);
  }
});

jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useSearchParams: () => [globalThis.__wfParams, globalThis.__wfSetParams],
  };
});

const setSearchParamsMock = globalThis.__wfSetParams;

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (typeof opts === 'string') return opts;
      // Support {{count}} / {{total}} / {{filtered}} interpolation
      if (opts && typeof opts === 'object') {
        return key + ': ' + Object.values(opts).join(',');
      }
      return key;
    },
  }),
}));

const taskService = require('../../services/taskService').default;
const dynamicWorkflowService = require('../../services/dynamicWorkflowService').default;

const sampleWorkflows = [
  {
    workflow_id: 'wf-task-1',
    task_id: 'task-1',
    type: 'agent_task',
    status: 'completed',
    objective: 'Generate a daily report',
    start_time: '2026-05-09T10:00:00Z',
    close_time: '2026-05-09T10:01:30Z',
    tokens_used: 1234,
    cost: 0.0234,
    source: 'agent_task',
  },
  {
    workflow_id: 'wf-monitor-1',
    type: 'InboxMonitorWorkflow',
    status: 'RUNNING',
    objective: 'Monitor inbox',
    start_time: '2026-05-09T11:00:00Z',
    source: 'temporal',
  },
];

const sampleStats = {
  total_workflows: 12,
  running_count: 3,
  completed_count: 7,
  failed_count: 2,
  total_tokens: 9876,
  total_cost: 1.23,
  temporal_available: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <WorkflowsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  globalThis.__wfParams = new URLSearchParams();
  taskService.listWorkflows.mockResolvedValue({ data: { workflows: sampleWorkflows } });
  taskService.getWorkflowStats.mockResolvedValue({ data: sampleStats });
  taskService.getTrace.mockResolvedValue({ data: { steps: [] } });
  taskService.getWorkflowHistory.mockResolvedValue({ data: { events: [] } });
  taskService.approve.mockResolvedValue({});
  taskService.reject.mockResolvedValue({});
  dynamicWorkflowService.list.mockResolvedValue([]);
});

afterAll(() => {
  jest.useRealTimers();
});

describe('WorkflowsPage', () => {
  test('renders the header and the default My Workflows tab', async () => {
    renderPage();
    expect(await screen.findByText('title')).toBeInTheDocument();
    expect(await screen.findByTestId('dynamic-workflows-tab')).toBeInTheDocument();
    // dynamicWorkflowService.list is fired on mount to feed RunsTab
    await waitFor(() => expect(dynamicWorkflowService.list).toHaveBeenCalled());
  });

  test('renders all five main tabs', async () => {
    renderPage();
    await screen.findByTestId('dynamic-workflows-tab');
    expect(screen.getByRole('tab', { name: /My Workflows/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Templates/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Runs/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /tabs\.executions/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /tabs\.designs/ })).toBeInTheDocument();
  });

  test('clicking Templates tab updates the search param', async () => {
    renderPage();
    await screen.findByTestId('dynamic-workflows-tab');
    fireEvent.click(screen.getByRole('tab', { name: /Templates/ }));
    expect(setSearchParamsMock).toHaveBeenCalledWith({ tab: 'templates' });
  });

  test('renders TemplatesTab when ?tab=templates', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=templates');
    renderPage();
    expect(await screen.findByTestId('templates-tab')).toBeInTheDocument();
  });

  test('renders RunsTab when ?tab=runs', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=runs');
    renderPage();
    expect(await screen.findByTestId('runs-tab')).toBeInTheDocument();
  });

  test('Designs tab renders the workflow definitions catalog', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=designs');
    renderPage();
    // Workflow card: "Platform · Task Execution"
    expect(
      await screen.findByText('Platform · Task Execution'),
    ).toBeInTheDocument();
    // Inbox Monitor and Code Task are also in the catalog
    expect(screen.getByText('Platform · Inbox Monitor')).toBeInTheDocument();
    expect(screen.getByText('Platform · Code Task (Claude Code)')).toBeInTheDocument();
  });

  test('Designs tab card expands to reveal the steps when clicked', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=designs');
    renderPage();
    const card = await screen.findByText('Platform · Task Execution');
    // Click the card header to expand.
    fireEvent.click(card.closest('.wf-card-header'));
    // After expand, individual step names render. 'recall_memory' is a
    // task-execution step.
    expect(await screen.findByText('recall_memory')).toBeInTheDocument();
  });

  test('Executions tab fetches workflows + stats on mount', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    await waitFor(() => {
      expect(taskService.listWorkflows).toHaveBeenCalled();
      expect(taskService.getWorkflowStats).toHaveBeenCalled();
    });
    // Stat values render from the loaded stats.
    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(screen.getByText('$1.23')).toBeInTheDocument();
  });

  test('Executions tab renders workflow rows from API', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    expect(await screen.findByText('Generate a daily report')).toBeInTheDocument();
    // Temporal workflows are grouped by type — InboxMonitorWorkflow shows
    // in both the row body and the type cell, so just assert at least one.
    const matches = screen.getAllByText('InboxMonitorWorkflow');
    expect(matches.length).toBeGreaterThan(0);
  });

  test('Executions tab status filter triggers refetch with status param', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    await screen.findByText('Generate a daily report');
    taskService.listWorkflows.mockClear();
    // The status select is one of the three Form.Select elements; pick the
    // one whose options include "completed".
    const selects = screen.getAllByRole('combobox');
    const statusSelect = selects.find((s) =>
      Array.from(s.options || []).some((o) => o.value === 'completed'),
    );
    fireEvent.change(statusSelect, { target: { value: 'completed' } });
    await waitFor(() => {
      expect(taskService.listWorkflows).toHaveBeenCalledWith({ status: 'completed' });
    });
  });

  test('Executions tab search filter narrows the visible rows', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    expect(await screen.findByText('Generate a daily report')).toBeInTheDocument();
    const searchBox = screen.getByPlaceholderText(
      'executions.filter.searchPlaceholder',
    );
    fireEvent.change(searchBox, { target: { value: 'inbox' } });
    // Agent task disappears, InboxMonitor remains.
    await waitFor(() =>
      expect(screen.queryByText('Generate a daily report')).not.toBeInTheDocument(),
    );
  });

  test('Executions tab clicking a row opens the detail modal', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    const objective = await screen.findByText('Generate a daily report');
    // Click the row (closest .workflow-table-row)
    fireEvent.click(objective.closest('.workflow-table-row'));
    // Modal opens — TaskTimeline placeholder mounts inside it.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByTestId('task-timeline')).toBeInTheDocument();
    // Trace fetch should fire for the selected task.
    await waitFor(() => expect(taskService.getTrace).toHaveBeenCalledWith('task-1'));
  });

  test('Executions tab refresh button re-fetches workflows + stats', async () => {
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    await screen.findByText('Generate a daily report');
    taskService.listWorkflows.mockClear();
    taskService.getWorkflowStats.mockClear();
    fireEvent.click(screen.getByRole('button', { name: /executions\.refresh/ }));
    await waitFor(() => {
      expect(taskService.listWorkflows).toHaveBeenCalled();
      expect(taskService.getWorkflowStats).toHaveBeenCalled();
    });
  });

  test('Executions tab handles fetch error without crashing', async () => {
    taskService.listWorkflows.mockRejectedValue(new Error('boom'));
    taskService.getWorkflowStats.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    // Refresh interval combobox still renders (component is alive).
    expect(
      await screen.findByRole('button', { name: /executions\.refresh/ }),
    ).toBeInTheDocument();
    errSpy.mockRestore();
  });

  test('Executions tab empty state when API returns no workflows', async () => {
    taskService.listWorkflows.mockResolvedValue({ data: { workflows: [] } });
    globalThis.__wfParams = new URLSearchParams('tab=executions');
    renderPage();
    // The total stat shows the loaded value, but the table body has no rows.
    await waitFor(() => expect(taskService.listWorkflows).toHaveBeenCalled());
    expect(
      await screen.findByText(/executions\.workflowsCount/),
    ).toBeInTheDocument();
  });
});
