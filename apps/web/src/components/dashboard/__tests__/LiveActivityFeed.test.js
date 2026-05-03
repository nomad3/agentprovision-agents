import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import LiveActivityFeed from '../LiveActivityFeed';

jest.mock('../../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

const api = require('../../../services/api').default;


describe('LiveActivityFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  test('hides itself entirely on 403 (admin-only audit endpoint)', async () => {
    api.get.mockRejectedValue({ response: { status: 403 } });
    const { container } = render(<LiveActivityFeed />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // Wait a microtask tick for the setError → re-render
    await waitFor(() => expect(container.firstChild).toBeNull());
  });

  test('renders empty state when no recent activity', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<LiveActivityFeed />);
    await waitFor(() =>
      expect(screen.getByText(/No agent activity in the last 5 minutes/)).toBeInTheDocument(),
    );
  });

  test('renders rows from audit response', async () => {
    api.get.mockResolvedValue({
      data: [
        {
          id: '1',
          invocation_type: 'chat',
          input_summary: 'Hello there',
          status: 'success',
          latency_ms: 240,
          cost_usd: 0.0123,
          created_at: new Date().toISOString(),
        },
      ],
    });
    render(<LiveActivityFeed />);
    await waitFor(() => expect(screen.getByText('chat')).toBeInTheDocument());
    expect(screen.getByText(/Hello there/)).toBeInTheDocument();
    expect(screen.getByText('240ms')).toBeInTheDocument();
    expect(screen.getByText('$0.0123')).toBeInTheDocument();
  });

  test('pause toggle stops the polling interval', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<LiveActivityFeed />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));

    // Advance through one polling cycle while live
    await act(async () => { jest.advanceTimersByTime(15_000); });
    expect(api.get).toHaveBeenCalledTimes(2);

    // Click pause
    fireEvent.click(screen.getByLabelText(/Pause polling/));

    // Subsequent intervals should NOT trigger fetches
    await act(async () => { jest.advanceTimersByTime(45_000); });
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Paused/)).toBeInTheDocument();
  });

  test('truncates long input_summary with ellipsis', async () => {
    const longInput = 'A'.repeat(120);
    api.get.mockResolvedValue({
      data: [{
        id: '1', invocation_type: 'chat', input_summary: longInput,
        status: 'success', created_at: new Date().toISOString(),
      }],
    });
    render(<LiveActivityFeed />);
    // Text is split across React fragments (dash + sliced + ellipsis);
    // assert on the outerHTML rather than a getByText regex.
    await waitFor(() => expect(screen.getByText('chat')).toBeInTheDocument());
    const list = document.querySelector('.live-activity-list');
    expect(list.textContent).toContain('A'.repeat(80));
    expect(list.textContent).toContain('…');
    // Original 120-char input was cut to 80 + ellipsis
    expect(list.textContent).not.toContain('A'.repeat(120));
  });

  test('omits cost label when cost_usd is 0 or missing', async () => {
    api.get.mockResolvedValue({
      data: [{
        id: '1', invocation_type: 'chat', input_summary: 'x',
        status: 'success', latency_ms: 100, cost_usd: 0,
        created_at: new Date().toISOString(),
      }],
    });
    render(<LiveActivityFeed />);
    await waitFor(() => expect(screen.getByText('chat')).toBeInTheDocument());
    expect(screen.queryByText(/\$0/)).toBeNull();
  });
});
