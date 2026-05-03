import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CostInsightsPage from '../CostInsightsPage';

jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));
jest.mock('../../components/Layout', () => ({ children }) => <>{children}</>);
// recharts ResponsiveContainer needs measured DOM — stub it for jsdom.
jest.mock('recharts', () => {
  const Real = jest.requireActual('recharts');
  return {
    ...Real,
    ResponsiveContainer: ({ children }) => <div data-testid="recharts-mock">{children}</div>,
  };
});

const api = require('../../services/api').default;


function renderPage() {
  return render(
    <MemoryRouter>
      <CostInsightsPage />
    </MemoryRouter>,
  );
}


const _emptyResponse = {
  range: { start: '2026-04-03', end: '2026-05-03' },
  granularity: 'day',
  group_by: 'agent',
  totals: { tokens: 0, cost_usd: 0, invocations: 0 },
  series: [],
  top_agents: [],
  quota_burn: null,
};


describe('CostInsightsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: _emptyResponse });
  });

  test('fetches with default range=30d, group_by=agent', async () => {
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const call = api.get.mock.calls[0];
    expect(call[1]?.params).toMatchObject({ range: '30d', group_by: 'agent', granularity: 'day' });
  });

  test('range chip click triggers refetch with new range', async () => {
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    fireEvent.click(screen.getByText('7 days'));
    await waitFor(() => {
      const last = api.get.mock.calls[api.get.mock.calls.length - 1];
      expect(last[1]?.params?.range).toBe('7d');
    });
  });

  test('group_by chip click triggers refetch with new group', async () => {
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    fireEvent.click(screen.getByText('Team'));
    await waitFor(() => {
      const last = api.get.mock.calls[api.get.mock.calls.length - 1];
      expect(last[1]?.params?.group_by).toBe('team');
    });
  });

  test('renders totals from response', async () => {
    api.get.mockResolvedValue({
      data: {
        ..._emptyResponse,
        totals: { tokens: 12345, cost_usd: 4.5678, invocations: 892 },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('$4.57')).toBeInTheDocument());
    expect(screen.getByText('12,345')).toBeInTheDocument();
    expect(screen.getByText('892')).toBeInTheDocument();
  });

  test('shows quota-burn banner when within 14 days of exhaustion', async () => {
    api.get.mockResolvedValue({
      data: {
        ..._emptyResponse,
        quota_burn: {
          monthly_limit_tokens: 1_000_000,
          tokens_used_mtd: 700_000,
          projected_exhaustion_date: '2026-05-15',
          days_until_exhaustion: 9,
        },
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Projected token-quota exhaustion/)).toBeInTheDocument());
    expect(screen.getByText(/9 day/)).toBeInTheDocument();
  });

  test('hides quota-burn banner when days_until is null (on track)', async () => {
    api.get.mockResolvedValue({
      data: {
        ..._emptyResponse,
        quota_burn: {
          monthly_limit_tokens: 1_000_000,
          tokens_used_mtd: 100_000,
          projected_exhaustion_date: null,
          days_until_exhaustion: null,
        },
      },
    });
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText(/Projected token-quota exhaustion/)).toBeNull();
  });

  test('renders top agents with cost from response', async () => {
    api.get.mockResolvedValue({
      data: {
        ..._emptyResponse,
        top_agents: [
          {
            id: '11111111-1111-1111-1111-111111111111',
            name: 'Acme Sales Bot',
            tokens: 50000,
            cost_usd: 1.2345,
            invocations: 250,
          },
        ],
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('Acme Sales Bot')).toBeInTheDocument());
    expect(screen.getByText('$1.2345')).toBeInTheDocument();
    expect(screen.getByText('250')).toBeInTheDocument();
  });

  test('shows empty-state when no series and no top agents', async () => {
    renderPage();
    // Wait for the empty-state to render (post-fetch). Just waiting on
    // api.get having been called doesn't mean the render has flushed.
    await waitFor(() => expect(screen.getByText(/No usage in this range/)).toBeInTheDocument());
    expect(screen.getByText(/No agents have any cost in this range/)).toBeInTheDocument();
  });

  test('renders error banner when API fails', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'cost api down' } } });
    renderPage();
    await waitFor(() => expect(screen.getByText('cost api down')).toBeInTheDocument());
  });
});
