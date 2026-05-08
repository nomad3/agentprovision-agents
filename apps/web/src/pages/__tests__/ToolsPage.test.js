import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ToolsPage from '../ToolsPage';

jest.mock('../../services/tool', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
  },
}));
jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

// Common UI primitives — render trivial proxies so we can test page logic.
const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('../../components/common', () => ({
  __esModule: true,
  EmptyState: ({ title, description, action }) => (
    <div data-testid="empty-state">
      <div>{title}</div>
      <div>{description}</div>
      {action}
    </div>
  ),
  LoadingSpinner: ({ text }) => <div role="status">{text}</div>,
  ConfirmModal: ({ show, onConfirm, onHide, title }) =>
    show ? (
      <div role="dialog" aria-label="confirm-modal">
        <div>{title}</div>
        <button type="button" onClick={onConfirm}>confirm</button>
        <button type="button" onClick={onHide}>cancel</button>
      </div>
    ) : null,
  useToast: () => mockToast,
}));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key) => key,
  }),
}));

const toolService = require('../../services/tool').default;

const sampleTools = [
  {
    id: 't-1',
    name: 'SQL Query',
    description: 'Run SQL queries against connected datasets',
    tool_type: 'api',
    configuration: {},
    authentication_required: false,
  },
  {
    id: 't-2',
    name: 'Web Scraper',
    description: 'Fetch and extract page content',
    tool_type: 'http',
    configuration: {},
    authentication_required: true,
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <ToolsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  toolService.getAll.mockResolvedValue({ data: sampleTools });
  toolService.create.mockResolvedValue({});
  toolService.update.mockResolvedValue({});
  toolService.delete.mockResolvedValue({});
});

describe('ToolsPage', () => {
  test('loads and renders the tools table', async () => {
    renderPage();
    await waitFor(() => expect(toolService.getAll).toHaveBeenCalled());
    expect(await screen.findByText('SQL Query')).toBeInTheDocument();
    expect(screen.getByText('Web Scraper')).toBeInTheDocument();
  });

  test('search input narrows the displayed tools', async () => {
    renderPage();
    await screen.findByText('SQL Query');
    const search = screen.getByPlaceholderText('searchPlaceholder');
    fireEvent.change(search, { target: { value: 'scraper' } });
    expect(screen.queryByText('SQL Query')).not.toBeInTheDocument();
    expect(screen.getByText('Web Scraper')).toBeInTheDocument();
  });

  test('shows the empty-state when no tools exist', async () => {
    toolService.getAll.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('noToolsYet')).toBeInTheDocument();
  });

  test('shows search-no-results state when search has no matches', async () => {
    renderPage();
    await screen.findByText('SQL Query');
    const search = screen.getByPlaceholderText('searchPlaceholder');
    fireEvent.change(search, { target: { value: 'nonexistent-tool' } });
    expect(screen.getByText('noToolsFound')).toBeInTheDocument();
  });

  test('clicking Create Tool opens the create modal', async () => {
    renderPage();
    await screen.findByText('SQL Query');
    fireEvent.click(screen.getByRole('button', { name: /createTool/ }));
    // Bootstrap Modal renders a dialog when open.
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  test('shows error toast when getAll fails', async () => {
    toolService.getAll.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('errors.load'));
    errSpy.mockRestore();
  });

  test('shows the loading spinner while data loads', () => {
    let resolveGet;
    toolService.getAll.mockImplementation(
      () => new Promise(res => { resolveGet = res; }),
    );
    renderPage();
    expect(screen.getByRole('status')).toBeInTheDocument();
    resolveGet({ data: [] });
  });
});
