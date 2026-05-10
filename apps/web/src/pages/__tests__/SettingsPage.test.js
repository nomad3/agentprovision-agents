import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from '../SettingsPage';

// ── Boundary mocks ────────────────────────────────────────────────────
jest.mock('../../services/api', () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

jest.mock('../../services/branding', () => ({
  __esModule: true,
  brandingService: {
    getFeatures: jest.fn(),
    getBranding: jest.fn(),
    updateBranding: jest.fn(),
    updateFeatures: jest.fn(),
  },
}));

// useAuth — frozen identity to avoid useEffect re-fires
jest.mock('../../App', () => {
  const refreshUser = jest.fn().mockResolvedValue();
  const authValue = {
    user: {
      id: 'u-1',
      email: 'admin@example.com',
      full_name: 'Admin User',
    },
    refreshUser,
  };
  return {
    __esModule: true,
    useAuth: () => authValue,
  };
});

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

const api = require('../../services/api').default;
const { brandingService } = require('../../services/branding');

const sampleFeatures = {
  max_agents: 10,
  max_agent_groups: 3,
  monthly_token_limit: 1000000,
  storage_limit_gb: 50,
  default_cli_platform: 'claude_code',
  use_memory_v2: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  brandingService.getFeatures.mockResolvedValue(sampleFeatures);
  api.get.mockImplementation((url) => {
    if (url === '/postgres/status') {
      return Promise.resolve({ data: { connected: true, tables: 117 } });
    }
    if (url === '/users/me/gesture-bindings') {
      return Promise.resolve({ data: { bindings: [], updated_at: null } });
    }
    return Promise.resolve({ data: {} });
  });
  api.put.mockResolvedValue({ data: {} });
  api.post.mockResolvedValue({ data: {} });
});

// Helper — finds the full name <input> by its current value (rendered from
// useAuth on first paint) since react-bootstrap doesn't wire htmlFor.
const findFullNameInput = () =>
  screen.findByPlaceholderText('Your display name');

describe('SettingsPage', () => {
  test('renders the header and the Profile tab by default', async () => {
    renderPage();
    expect(await screen.findByText('Settings')).toBeInTheDocument();
    const fullNameInput = await findFullNameInput();
    expect(fullNameInput).toHaveValue('Admin User');
    // Email is read-only and pulled from useAuth
    const emailInput = screen.getByDisplayValue('admin@example.com');
    expect(emailInput).toBeDisabled();
  });

  test('loads tenant features on mount', async () => {
    renderPage();
    await waitFor(() => expect(brandingService.getFeatures).toHaveBeenCalled());
  });

  test('saves the profile when full name is changed', async () => {
    renderPage();
    const input = await findFullNameInput();
    fireEvent.change(input, { target: { value: 'New Name' } });
    fireEvent.click(screen.getByRole('button', { name: /Save profile/ }));
    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith('/users/me', { full_name: 'New Name' });
    });
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument();
  });

  test('save profile button is disabled when full name is unchanged', async () => {
    renderPage();
    await findFullNameInput();
    const saveBtn = screen.getByRole('button', { name: /Save profile/ });
    expect(saveBtn).toBeDisabled();
  });

  test('shows error alert when profile save fails', async () => {
    api.put.mockRejectedValue({ response: { data: { detail: 'profile boom' } } });
    renderPage();
    const input = await findFullNameInput();
    fireEvent.change(input, { target: { value: 'Updated' } });
    fireEvent.click(screen.getByRole('button', { name: /Save profile/ }));
    expect(await screen.findByText('profile boom')).toBeInTheDocument();
  });

  test('password reset button posts to /auth/password-recovery and shows confirmation', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('button', { name: /Send reset email/ }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/auth/password-recovery/admin%40example.com',
      );
    });
    expect(await screen.findByText(/Check your inbox/)).toBeInTheDocument();
  });

  test('switches to the Workspace tab and renders the branding link', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Workspace/ }));
    expect(await screen.findByText(/Workspace branding/)).toBeInTheDocument();
    expect(screen.getByText(/Open branding editor/)).toBeInTheDocument();
  });

  test('switches to the Plan & Limits tab and renders feature rows', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Plan & Limits/ }));
    expect(await screen.findByText('Max agents')).toBeInTheDocument();
    expect(screen.getByText('Monthly tokens')).toBeInTheDocument();
    // CLI label resolves to friendly name
    expect(screen.getByText('Claude Code')).toBeInTheDocument();
    // Memory v2 enabled badge
    expect(screen.getByText('Enabled')).toBeInTheDocument();
  });

  test('Plan tab shows the warning when getFeatures fails', async () => {
    brandingService.getFeatures.mockRejectedValue(new Error('boom'));
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Plan & Limits/ }));
    expect(
      await screen.findByText(/Could not load tenant features/),
    ).toBeInTheDocument();
  });

  test('Database tab fetches postgres status and renders the connected badge', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Database/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/postgres/status'));
    expect(await screen.findByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('117')).toBeInTheDocument();
  });

  test('Initialize button on Database tab posts to /postgres/initialize', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Database/ }));
    const initBtn = await screen.findByRole('button', {
      name: /Initialize \/ migrate/,
    });
    fireEvent.click(initBtn);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/postgres/initialize');
    });
    expect(
      await screen.findByText(/PostgreSQL initialized successfully/),
    ).toBeInTheDocument();
  });

  test('Initialize button surfaces error message on failure', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/postgres/initialize') {
        return Promise.reject({ response: { data: { detail: 'init boom' } } });
      }
      return Promise.resolve({ data: {} });
    });
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Database/ }));
    const initBtn = await screen.findByRole('button', {
      name: /Initialize \/ migrate/,
    });
    fireEvent.click(initBtn);
    expect(await screen.findByText('init boom')).toBeInTheDocument();
  });

  test('Gestures tab loads bindings from the API', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/users/me/gesture-bindings') {
        return Promise.resolve({
          data: {
            bindings: [{ name: 'wave' }, { name: 'pinch' }],
            updated_at: '2026-05-09T10:00:00Z',
          },
        });
      }
      if (url === '/postgres/status') {
        return Promise.resolve({ data: { connected: true } });
      }
      return Promise.resolve({ data: {} });
    });
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Gestures/ }));
    expect(await screen.findByText('2 bindings synced.')).toBeInTheDocument();
  });

  test('Gestures tab shows empty state when no bindings', async () => {
    renderPage();
    await findFullNameInput();
    fireEvent.click(screen.getByRole('tab', { name: /Gestures/ }));
    // bindings: [] resolves into "0 bindings synced."
    expect(await screen.findByText('0 bindings synced.')).toBeInTheDocument();
    expect(
      screen.getByText(/Open the Luna desktop client to record gestures/),
    ).toBeInTheDocument();
  });
});
