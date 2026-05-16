/*
 * TerminalPanel tests — Phase B coverage of the multi-pane terminal.
 *
 * The panel reads from SessionEventsContext, so we render it inside a
 * lightweight test provider that exposes a setter — that gives the
 * tests a way to inject `cli_subprocess_stream` events without having
 * to stand up the real SSE hook.
 *
 * jsdom doesn't compute layout; for the mobile-fallback test we force
 * `window.innerWidth` below the 992 breakpoint and dispatch a resize.
 */
import { useState } from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import TerminalPanel from '../TerminalPanel';
import SessionEventsContext from '../SessionEventsContext';

// ── localStorage keys we own (kept in sync with TerminalPanel.js) ──
const LS_GROUPS = 'apControl.terminalGroups';
const LS_FOCUSED = 'apControl.terminalFocusedGroupId';
const LS_OPEN = 'apControl.terminalOpen';

const setViewportWidth = (width) => {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  });
  window.dispatchEvent(new Event('resize'));
};

const makeStreamEvent = (platform = 'claude_code', chunk = 'hello\n', seq = 1) => ({
  type: 'cli_subprocess_stream',
  payload: { platform, chunk, fd: 'stdout' },
  seq_no: seq,
  ts: Date.now(),
});

// Test harness: a tiny stateful Provider that lets the test feed
// events into TerminalPanel without standing up the real SSE hook.
const Harness = ({ initialEvents = [], status = 'idle', onApi }) => {
  const [events, setEvents] = useState(initialEvents);
  // Surface the setter to the test via a ref-style callback so we can
  // dispatch synthetic events mid-test.
  if (onApi) onApi(setEvents);
  return (
    <SessionEventsContext.Provider value={{ events, status }}>
      <TerminalPanel sessionId="sess-1" />
    </SessionEventsContext.Provider>
  );
};

const renderPanel = (props = {}) => {
  let apiSetter = null;
  const utils = render(<Harness {...props} onApi={(s) => { apiSetter = s; }} />);
  return { ...utils, setEvents: (...args) => act(() => apiSetter(...args)) };
};

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1400);
});

describe('TerminalPanel — initial render & single group', () => {
  test('renders one group on first mount with no focus border', () => {
    renderPanel();
    // Expand the panel so the body renders (default is collapsed).
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    // Solo group: focused but no .tg-card-focused border (visually
    // suppressed because there's no neighbour to distinguish from).
    // We assert by checking only one .tg-card exists.
    // eslint-disable-next-line testing-library/no-node-access
    const cards = document.querySelectorAll('.tg-card');
    expect(cards.length).toBe(1);
  });
});

describe('TerminalPanel — split + close', () => {
  test('clicking Split column adds a second group and focuses it', () => {
    renderPanel();
    // Expand first.
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    fireEvent.click(screen.getByLabelText(/split column/i));
    // eslint-disable-next-line testing-library/no-node-access
    const cards = document.querySelectorAll('.tg-card');
    expect(cards.length).toBe(2);
    // The newer (rightmost) group should carry the focus indicator
    // class — VSCode behaviour: split focuses the new group.
    expect(cards[1].classList.contains('tg-card-focused')).toBe(true);
    expect(cards[0].classList.contains('tg-card-focused')).toBe(false);
  });

  test('clicking Close split with N=2 returns to a single group', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    fireEvent.click(screen.getByLabelText(/split column/i));
    expect(screen.getByLabelText(/close focused group/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/close focused group/i));
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(1);
    // Close button vanishes when only one group remains.
    expect(screen.queryByLabelText(/close focused group/i)).toBeNull();
  });

  test('Split column button is disabled when N=4 (max)', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    const splitBtn = screen.getByLabelText(/split column/i);
    // Three more splits → N=4.
    fireEvent.click(splitBtn);
    fireEvent.click(splitBtn);
    fireEvent.click(splitBtn);
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(4);
    expect(splitBtn).toBeDisabled();
  });
});

describe('TerminalPanel — localStorage persistence', () => {
  test('groups state is persisted and rehydrated on remount', () => {
    const { unmount } = renderPanel();
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    fireEvent.click(screen.getByLabelText(/split column/i));
    // Persisted shape: array of {id, activeTabKey}.
    const raw = window.localStorage.getItem(LS_GROUPS);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw);
    expect(parsed).toHaveLength(2);
    expect(parsed[0].id).toBeTruthy();
    expect(window.localStorage.getItem(LS_FOCUSED)).toBe(parsed[1].id);

    unmount();
    // Remount — groups should rehydrate to 2 panes. The panel was
    // open at unmount, so `apControl.terminalOpen=true` is persisted
    // and the body is already expanded on remount; no expand-click
    // needed.
    renderPanel();
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(2);
  });

  test('collapse persists and restores on remount', () => {
    const { unmount } = renderPanel();
    // Expand → collapse.
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    fireEvent.click(screen.getByLabelText(/collapse terminal panel/i));
    expect(window.localStorage.getItem(LS_OPEN)).toBe('false');
    unmount();
    renderPanel();
    // After remount with persisted open=false, no tg-card visible.
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(0);
    // The expand-affordance is still in the header.
    expect(screen.getByLabelText(/expand terminal panel/i)).toBeInTheDocument();
  });
});

describe('TerminalPanel — auto-open on first chunk', () => {
  test('cli_subprocess_stream event opens a collapsed panel', () => {
    const { setEvents } = renderPanel({ initialEvents: [], status: 'open' });
    // Sanity: starts collapsed.
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(0);
    // Dispatch a synthetic stream event.
    setEvents([makeStreamEvent('claude_code', 'output\n', 1)]);
    // Now expanded with one group rendered.
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(1);
  });
});

describe('TerminalPanel — mobile fallback', () => {
  test('below 992 px viewport, only focused group renders (no inner split)', () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText(/expand terminal panel/i));
    fireEvent.click(screen.getByLabelText(/split column/i));
    // Desktop: 2 groups visible.
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(2);
    // Switch to mobile width.
    act(() => setViewportWidth(800));
    // eslint-disable-next-line testing-library/no-node-access
    expect(document.querySelectorAll('.tg-card').length).toBe(1);
  });
});
