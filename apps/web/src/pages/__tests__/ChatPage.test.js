import { render, screen, fireEvent, waitFor, within, act, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ChatPage from '../ChatPage';

// ── Boundary mocks ────────────────────────────────────────────────────
// Service modules are tested in Phase 2; mock them at the boundary.
jest.mock('../../services/chat', () => ({
  __esModule: true,
  default: {
    listSessions: jest.fn(),
    listMessages: jest.fn(),
    createSession: jest.fn(),
    postMessage: jest.fn(),
    postMessageStream: jest.fn(),
    postMessageWithFile: jest.fn(),
    getSessionEntities: jest.fn(),
  },
}));

jest.mock('../../services/agent', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(),
  },
}));

// useAuth from App — frozen constant object so identity checks across
// renders don't trigger useEffect re-runs on every render.
jest.mock('../../App', () => {
  const authValue = { user: { access_token: 'tok-test' } };
  return {
    __esModule: true,
    useAuth: () => authValue,
  };
});

// LunaPresenceContext — return a noop presence so the page doesn't crash.
jest.mock('../../context/LunaPresenceContext', () => ({
  useLunaPresence: () => ({
    presence: { state: 'idle', mood: 'calm' },
  }),
}));

// Voice & speech hooks — fully neutralised (they touch native APIs).
jest.mock('../../hooks/useVoiceInput', () => ({
  useVoiceInput: () => ({
    isRecording: false,
    start: jest.fn(),
    stop: jest.fn(),
    recordedBlob: null,
  }),
}));
jest.mock('../../hooks/useSpeechSynthesis', () => ({
  useSpeechSynthesis: () => ({
    speak: jest.fn(),
    cancel: jest.fn(),
  }),
}));

// Layout pulls in many providers; render its children.
jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

// CollaborationPanel makes its own SSE call — out of scope here.
jest.mock('../../components/CollaborationPanel', () => () => (
  <div data-testid="collab-panel" />
));
jest.mock('../../components/RoutingFooter', () => () => (
  <div data-testid="routing-footer" />
));
jest.mock('../../components/chat/FeedbackActions', () => () => (
  <div data-testid="feedback-actions" />
));
jest.mock('../../components/chat/ReportVisualization', () => () => null);

// Markdown renders as plain content for assertion simplicity.
jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (typeof opts === 'string') return opts;
      if (opts && typeof opts === 'object') {
        // Crude interpolation for {{count}} / {{name}}
        return key + (opts.count !== undefined ? `: ${opts.count}` : '');
      }
      return key;
    },
  }),
}));

// SSE session events fetch — make it a no-op promise that never resolves
// so the AbortController path is exercised on cleanup.
const originalFetch = global.fetch;

const chatService = require('../../services/chat').default;
const agentService = require('../../services/agent').default;

const sampleAgents = [
  { id: 'agent-1', name: 'Luna', description: 'Personal assistant' },
  { id: 'agent-2', name: 'Cardiac Analyst', description: 'DACVIM evaluator' },
];

const sampleSessions = [
  { id: 'sess-1', title: 'First chat', agent_id: 'agent-1' },
  { id: 'sess-2', title: 'Second chat', agent_id: 'agent-2' },
];

const sampleMessages = [
  {
    id: 'm-1',
    role: 'user',
    content: 'Hello there',
    created_at: '2026-05-05T10:00:00Z',
  },
  {
    id: 'm-2',
    role: 'assistant',
    content: 'Hi! How can I help?',
    created_at: '2026-05-05T10:00:01Z',
    context: { entities_extracted: 2 },
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <ChatPage />
    </MemoryRouter>,
  );
}

afterAll(() => {
  global.fetch = originalFetch;
});

beforeEach(() => {
  jest.clearAllMocks();
  // Stub fetch for the session-events SSE side effect and the
  // collaborations rehydrate request. Returns an unresolved promise
  // so we don't trigger any post-render state from it.
  global.fetch = jest.fn(() => new Promise(() => {}));
  // jsdom doesn't implement scrollIntoView; ChatPage scrolls on every
  // render, so stub it on the prototype.
  Element.prototype.scrollIntoView = jest.fn();
  agentService.getAll.mockResolvedValue({ data: sampleAgents });
  chatService.listSessions.mockResolvedValue({ data: sampleSessions });
  chatService.listMessages.mockResolvedValue({ data: sampleMessages });
  chatService.createSession.mockResolvedValue({
    data: { id: 'sess-new', title: 'Brand new', agent_id: 'agent-1' },
  });
  chatService.postMessageStream.mockImplementation(
    (sessionId, content, onToken, onUserSaved, onDone, onError) => {
      // Return an AbortController-like
      return { abort: jest.fn() };
    },
  );
  chatService.postMessageWithFile.mockResolvedValue({
    data: {
      user_message: { id: 'u-x', role: 'user', content: 'file', created_at: '2026-05-05T11:00:00Z' },
      assistant_message: { id: 'a-x', role: 'assistant', content: 'got it', created_at: '2026-05-05T11:00:01Z' },
    },
  });
  chatService.getSessionEntities.mockResolvedValue({ data: [] });
});

describe('ChatPage', () => {
  test('loads sessions + agents on mount and renders the session list', async () => {
    renderPage();
    await waitFor(() => expect(chatService.listSessions).toHaveBeenCalled());
    expect(agentService.getAll).toHaveBeenCalled();
    // Wait for both session items to render in the sidebar list (the
    // sidebar has a brief loading spinner before sessions resolve).
    await waitFor(() => {
      const matches = screen.getAllByText('First chat');
      expect(matches.length).toBeGreaterThan(0);
    });
    await waitFor(() => expect(screen.getByText('Second chat')).toBeInTheDocument());
  });

  test('auto-selects the first session and loads its messages', async () => {
    renderPage();
    await waitFor(() => expect(chatService.listMessages).toHaveBeenCalledWith('sess-1'));
    expect(await screen.findByText('Hello there')).toBeInTheDocument();
    expect(screen.getByText('Hi! How can I help?')).toBeInTheDocument();
  });

  test('selecting a different session loads its messages', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Second chat')).toBeInTheDocument());
    chatService.listMessages.mockClear();
    chatService.listMessages.mockResolvedValue({ data: [] });
    fireEvent.click(screen.getByText('Second chat'));
    await waitFor(() => expect(chatService.listMessages).toHaveBeenCalledWith('sess-2'));
  });

  test('opens the new-session modal with title + agent picker', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Second chat')).toBeInTheDocument());
    const newBtns = screen.getAllByRole('button', { name: /newSession/i });
    fireEvent.click(newBtns[0]);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('createModal.title')).toBeInTheDocument();
    // Title input is the only textbox in the dialog.
    expect(within(dialog).getByRole('textbox')).toBeInTheDocument();
    // Agent options come from agentService.getAll, rendered as <option>.
    expect(within(dialog).getByRole('combobox')).toBeInTheDocument();
    expect(within(dialog).getByText('Luna')).toBeInTheDocument();
    expect(within(dialog).getByText('Cardiac Analyst')).toBeInTheDocument();
  });

  test('submitting the new-session form calls createSession with the form payload', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Second chat')).toBeInTheDocument());
    const newBtns = screen.getAllByRole('button', { name: /newSession/i });
    fireEvent.click(newBtns[0]);
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox'), {
      target: { value: 'My new session', name: 'title' },
    });
    fireEvent.change(within(dialog).getByRole('combobox'), {
      target: { value: 'agent-1', name: 'agentId' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'createModal.create' }));
    await waitFor(() => {
      expect(chatService.createSession).toHaveBeenCalledWith({
        title: 'My new session',
        agent_id: 'agent-1',
      });
    });
  });

  test('shows error alert when createSession fails', async () => {
    chatService.createSession.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    await waitFor(() => expect(screen.getByText('Second chat')).toBeInTheDocument());
    const newBtns = screen.getAllByRole('button', { name: /newSession/i });
    fireEvent.click(newBtns[0]);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'createModal.create' }));
    expect(await screen.findByText('errors.createSession')).toBeInTheDocument();
    errSpy.mockRestore();
  });

  test('typing a message and submitting triggers postMessageStream', async () => {
    renderPage();
    await screen.findByText('Hello there');
    const input = await screen.findByRole('textbox');
    fireEvent.change(input, { target: { value: 'How are you?' } });
    // Submit the form by pressing Enter / submitting via the form element.
    const form = input.closest('form');
    fireEvent.submit(form);
    await waitFor(() => {
      expect(chatService.postMessageStream).toHaveBeenCalledWith(
        'sess-1',
        'How are you?',
        expect.any(Function),
        expect.any(Function),
        expect.any(Function),
        expect.any(Function),
      );
    });
  });

  test('streaming token callback appends streaming text to the conversation', async () => {
    let captured = {};
    chatService.postMessageStream.mockImplementation(
      (sessionId, content, onToken, onUserSaved, onDone, onError) => {
        captured = { onToken, onUserSaved, onDone, onError };
        return { abort: jest.fn() };
      },
    );
    renderPage();
    await screen.findByText('Hello there');
    const input = await screen.findByRole('textbox');
    fireEvent.change(input, { target: { value: 'Stream test' } });
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(captured.onToken).toBeDefined());
    act(() => {
      captured.onToken('Partial ');
      captured.onToken('response');
    });
    expect(await screen.findByText(/Partial response/)).toBeInTheDocument();
  });

  test('stream error surfaces via globalError alert', async () => {
    let captured = {};
    chatService.postMessageStream.mockImplementation(
      (sessionId, content, onToken, onUserSaved, onDone, onError) => {
        captured = { onToken, onUserSaved, onDone, onError };
        return { abort: jest.fn() };
      },
    );
    renderPage();
    await screen.findByText('Hello there');
    const input = await screen.findByRole('textbox');
    fireEvent.change(input, { target: { value: 'Trigger error' } });
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(captured.onError).toBeDefined());
    act(() => captured.onError('Stream failed: timeout'));
    expect(await screen.findByText(/Stream failed: timeout/)).toBeInTheDocument();
  });

  test('renders the routing footer for assistant messages', async () => {
    renderPage();
    await screen.findByText('Hi! How can I help?');
    // The mocked RoutingFooter renders a stub with this testid.
    const footers = await screen.findAllByTestId('routing-footer');
    expect(footers.length).toBeGreaterThan(0);
  });

  test('handles sessions=[] empty state without crashing', async () => {
    chatService.listSessions.mockResolvedValue({ data: [] });
    renderPage();
    await waitFor(() => expect(chatService.listSessions).toHaveBeenCalled());
    // Header still renders the page title (default-value fallback in t()).
    expect(await screen.findByText('AI Chat')).toBeInTheDocument();
    // Empty-state message shows in the session list.
    await waitFor(() =>
      expect(screen.getByText('noSessions')).toBeInTheDocument(),
    );
  });

  test('shows error when listSessions fails', async () => {
    chatService.listSessions.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    expect(await screen.findByText('errors.loadSessions')).toBeInTheDocument();
    errSpy.mockRestore();
  });

  test('clean-up: aborts any active stream on unmount', async () => {
    const abortFn = jest.fn();
    chatService.postMessageStream.mockImplementation(() => ({ abort: abortFn }));
    const { unmount } = renderPage();
    await screen.findByText('Hello there');
    const input = await screen.findByRole('textbox');
    fireEvent.change(input, { target: { value: 'Streaming...' } });
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(chatService.postMessageStream).toHaveBeenCalled());
    unmount();
    expect(abortFn).toHaveBeenCalled();
  });
});
