import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';

const apiJsonMock = vi.fn();

vi.mock('../../api', () => ({
  apiJson: (...args) => apiJsonMock(...args),
}));

import MemoryPanel from '../MemoryPanel';

beforeEach(() => {
  apiJsonMock.mockReset();
});

describe('MemoryPanel', () => {
  it('renders nothing when not visible', () => {
    const { container } = render(<MemoryPanel visible={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    expect(apiJsonMock).not.toHaveBeenCalled();
  });

  it('shows loading state while fetching episodes', async () => {
    let resolveFn;
    apiJsonMock.mockReturnValue(new Promise((r) => { resolveFn = r; }));
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    resolveFn([]);
    await waitFor(() => expect(screen.queryByText(/loading/i)).not.toBeInTheDocument());
  });

  it('fetches episodes from the recall endpoint when shown', async () => {
    apiJsonMock.mockResolvedValue([]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/episodes?limit=10');
    });
  });

  it('renders the empty state when no episodes are returned', async () => {
    apiJsonMock.mockResolvedValue([]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/no episodes yet/i)).toBeInTheDocument();
    });
  });

  it('renders an episode card with summary and entities', async () => {
    apiJsonMock.mockResolvedValue([
      {
        id: 'ep-1',
        summary: 'Met with the cardiology team about Brett',
        mood: 'positive',
        source_channel: 'whatsapp',
        created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
        key_entities: ['Brett', 'cardiology', 'Levi'],
      },
    ]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/Met with the cardiology team about Brett/)).toBeInTheDocument();
    });
    expect(screen.getByText('Brett')).toBeInTheDocument();
    expect(screen.getByText('cardiology')).toBeInTheDocument();
    expect(screen.getByText('whatsapp')).toBeInTheDocument();
  });

  it('limits entity tags to 5 even when more are returned', async () => {
    apiJsonMock.mockResolvedValue([
      {
        id: 'ep-2',
        summary: 'Lots of entities',
        created_at: new Date().toISOString(),
        key_entities: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      },
    ]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/lots of entities/i)).toBeInTheDocument());
    // Only the first 5 should render
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('e')).toBeInTheDocument();
    expect(screen.queryByText('f')).not.toBeInTheDocument();
    expect(screen.queryByText('g')).not.toBeInTheDocument();
  });

  it('renders different mood markers for known moods', async () => {
    apiJsonMock.mockResolvedValue([
      { id: '1', summary: 'positive', mood: 'positive', created_at: new Date().toISOString() },
      { id: '2', summary: 'frustrated', mood: 'frustrated', created_at: new Date().toISOString() },
      { id: '3', summary: 'curious', mood: 'curious', created_at: new Date().toISOString() },
      { id: '4', summary: 'unknown', mood: 'whatever', created_at: new Date().toISOString() },
    ]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('positive')).toBeInTheDocument());
    // The mood icons are short ASCII glyphs rendered next to the summary.
    expect(screen.getByText('+')).toBeInTheDocument();
    expect(screen.getByText('!')).toBeInTheDocument();
    expect(screen.getByText('?')).toBeInTheDocument();
    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('falls back to "chat" when source_channel is missing', async () => {
    apiJsonMock.mockResolvedValue([
      { id: 'ep-3', summary: 'no channel', created_at: new Date().toISOString() },
    ]);
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('chat')).toBeInTheDocument());
  });

  it('triggers onClose when the close button is clicked', async () => {
    apiJsonMock.mockResolvedValue([]);
    const onClose = vi.fn();
    render(<MemoryPanel visible={true} onClose={onClose} />);
    await waitFor(() => expect(screen.getByText(/no episodes/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'x' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('swallows fetch errors and ends loading', async () => {
    apiJsonMock.mockRejectedValue(new Error('boom'));
    render(<MemoryPanel visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.queryByText(/loading/i)).not.toBeInTheDocument());
    expect(screen.getByText(/no episodes yet/i)).toBeInTheDocument();
  });
});
