import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// Module-level mocks for ChatInterface dependencies.
const apiJsonMock = vi.fn();
const sendMock = vi.fn();
let streamState = { streaming: false, chunks: '' };

vi.mock('../../api', () => ({
  apiJson: (...args) => apiJsonMock(...args),
  API_BASE: 'http://test.local',
}));

vi.mock('../../hooks/useLunaStream', () => ({
  useLunaStream: () => ({
    send: sendMock,
    streaming: streamState.streaming,
    chunks: streamState.chunks,
  }),
}));

// MemoryPanel does its own fetch on mount-when-visible. The chat tests don't
// need to verify its behaviour, so render a stub.
vi.mock('../MemoryPanel', () => ({
  default: ({ visible }) => (visible ? <div data-testid="memory-panel-stub" /> : null),
}));

// react-markdown is imported inside ChatInterface — render a passthrough so
// streaming chunks are still observable as text.
vi.mock('react-markdown', () => ({
  default: ({ children }) => <div data-testid="markdown">{children}</div>,
}));
vi.mock('remark-gfm', () => ({ default: () => () => {} }));

// scrollIntoView isn't implemented in jsdom.
window.HTMLElement.prototype.scrollIntoView = vi.fn();

import ChatInterface from '../ChatInterface';

beforeEach(() => {
  apiJsonMock.mockReset();
  sendMock.mockReset();
  streamState = { streaming: false, chunks: '' };
  window.HTMLElement.prototype.scrollIntoView.mockClear();
});

describe('ChatInterface', () => {
  it('loads sessions on mount and renders them in the sidebar', async () => {
    apiJsonMock.mockResolvedValueOnce([
      { id: 's-1', title: 'First chat' },
      { id: 's-2', title: 'Second chat' },
    ]);
    apiJsonMock.mockResolvedValueOnce([]); // selectSession messages fetch
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('First chat')).toBeInTheDocument());
    expect(screen.getByText('Second chat')).toBeInTheDocument();
    expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/sessions');
  });

  it('renders the welcome screen when there are no messages and no session', async () => {
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/sessions'));
    expect(screen.getByText(/Luna OS Spatial Workstation/i)).toBeInTheDocument();
    expect(screen.getByText(/Cmd\+Shift\+L/)).toBeInTheDocument();
  });

  it('renders messages from the active session', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([
      { id: 'm-1', role: 'user', content: 'Hello Luna' },
      { id: 'm-2', role: 'assistant', content: 'Hello, friend.' },
    ]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('Hello Luna')).toBeInTheDocument());
    expect(screen.getByText('Hello, friend.')).toBeInTheDocument();
  });

  it('renders recalled-entity tags on assistant messages when present', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([
      {
        id: 'm-2',
        role: 'assistant',
        content: 'Recall result',
        context: { recalled_entity_names: ['Brett', 'Cardio'] },
      },
    ]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('Brett')).toBeInTheDocument());
    expect(screen.getByText('Cardio')).toBeInTheDocument();
  });

  it('disables Send and the input when streaming', async () => {
    streamState.streaming = true;
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalled());
    expect(screen.getByPlaceholderText(/message luna/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /\.\.\.+/ })).toBeDisabled();
  });

  it('shows the streaming bubble while chunks are being received', async () => {
    streamState.streaming = true;
    streamState.chunks = 'partial token stream...';
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalled());
    expect(screen.getByText('partial token stream...')).toBeInTheDocument();
  });

  it('sends a message: appends optimistic user bubble and calls send()', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([]); // initial messages
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('Chat')).toBeInTheDocument());

    sendMock.mockResolvedValue();
    const input = screen.getByPlaceholderText(/message luna/i);
    fireEvent.change(input, { target: { value: 'Hi there' } });
    fireEvent.click(screen.getByRole('button', { name: /^send$/i }));

    await waitFor(() => expect(screen.getByText('Hi there')).toBeInTheDocument());
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock.mock.calls[0][0]).toBe('s-1');
    expect(sendMock.mock.calls[0][1]).toBe('Hi there');
    expect(input.value).toBe('');
  });

  it('does not send empty messages', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('Chat')).toBeInTheDocument());

    const sendBtn = screen.getByRole('button', { name: /^send$/i });
    expect(sendBtn).toBeDisabled();
    fireEvent.click(sendBtn);
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('auto-creates a session when sending with no active session', async () => {
    apiJsonMock.mockResolvedValueOnce([]); // no existing sessions
    render(<ChatInterface />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));

    apiJsonMock.mockResolvedValueOnce({ id: 'new-s', title: 'Luna Chat' });
    sendMock.mockResolvedValue();
    fireEvent.change(screen.getByPlaceholderText(/message luna/i), { target: { value: 'Hello' } });
    fireEvent.submit(document.querySelector('form'));

    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/sessions', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ title: 'Luna Chat' }),
      }));
    });
    await waitFor(() => expect(sendMock).toHaveBeenCalledWith('new-s', 'Hello', expect.any(Object)));
  });

  it('creates a new chat session when "+ New Chat" is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce([]); // no sessions
    render(<ChatInterface />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalled());

    apiJsonMock.mockResolvedValueOnce({ id: 's-new', title: 'Luna Chat' });
    apiJsonMock.mockResolvedValueOnce([]); // selectSession messages fetch

    fireEvent.click(screen.getByRole('button', { name: /\+ new chat/i }));
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/sessions', expect.objectContaining({
        method: 'POST',
      }));
    });
    await waitFor(() => expect(screen.getByText('Luna Chat')).toBeInTheDocument());
  });

  it('opens the memory panel stub when the brain button is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('Chat')).toBeInTheDocument());
    expect(screen.queryByTestId('memory-panel-stub')).not.toBeInTheDocument();
    fireEvent.click(document.querySelector('.memory-toggle'));
    expect(screen.getByTestId('memory-panel-stub')).toBeInTheDocument();
  });

  it('switches sessions when a sidebar entry is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce([
      { id: 's-1', title: 'Alpha' },
      { id: 's-2', title: 'Beta' },
    ]);
    apiJsonMock.mockResolvedValueOnce([{ id: 'm-1', role: 'user', content: 'In Alpha' }]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('In Alpha')).toBeInTheDocument());

    apiJsonMock.mockResolvedValueOnce([{ id: 'm-2', role: 'user', content: 'In Beta' }]);
    fireEvent.click(screen.getByText('Beta'));
    await waitFor(() => expect(screen.getByText('In Beta')).toBeInTheDocument());
    expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/chat/sessions/s-2/messages');
  });

  it('shows the handoff banner when a handoff prop is provided', async () => {
    apiJsonMock.mockResolvedValueOnce([]);
    render(<ChatInterface handoff={{ id: 'h-1' }} />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalled());
    expect(screen.getByText(/Continuing from another device/i)).toBeInTheDocument();
  });

  it('scrolls to bottom when messages change', async () => {
    apiJsonMock.mockResolvedValueOnce([{ id: 's-1', title: 'Chat' }]);
    apiJsonMock.mockResolvedValueOnce([
      { id: 'm-1', role: 'user', content: 'first' },
    ]);
    render(<ChatInterface />);
    await waitFor(() => expect(screen.getByText('first')).toBeInTheDocument());
    expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it('logs an error and falls back gracefully when sessions fetch fails', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    apiJsonMock.mockRejectedValueOnce(new Error('connection refused'));
    render(<ChatInterface />);
    await waitFor(() => expect(errSpy).toHaveBeenCalled());
    // Welcome screen should still render
    expect(screen.getByText(/Luna OS Spatial Workstation/i)).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
