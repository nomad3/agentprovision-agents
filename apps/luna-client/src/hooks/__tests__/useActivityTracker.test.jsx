import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

const apiFetchMock = vi.fn();
const listeners = {};

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

vi.mock('../../utils/shellIdentity', () => ({
  getCachedShellId: () => null,
  getOrCreateShellId: () => Promise.resolve('desktop-test-shell'),
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn((eventName, callback) => {
    listeners[eventName] = callback;
    return Promise.resolve(vi.fn());
  }),
}));

import { useActivityTracker } from '../useActivityTracker';

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue({});
  Object.keys(listeners).forEach((key) => delete listeners[key]);
});

describe('useActivityTracker', () => {
  it('forwards sanitized macOS monitor events to the API and local UI bus', async () => {
    const domListener = vi.fn();
    window.addEventListener('luna:activity-event', domListener);

    renderHook(() => useActivityTracker());

    await waitFor(() => expect(listeners['activity-event']).toBeTruthy());
    await act(async () => {});

    await act(async () => {
      listeners['activity-event']({
        payload: {
          schema: 'agentprovision.macos_app_monitor_event.v1',
          event_id: '11111111-1111-4111-8111-111111111111',
          type: 'app_switch',
          from_app: 'Code',
          to_app: 'Terminal',
          duration_secs: 3,
          timestamp: 123,
          observed_at_ms: 123000,
          active_context_id: 'Terminal:abc123',
          window_title_present: true,
          window_title_chars: 24,
          window_title: 'secret repo title',
          subprocess: { active_processes: [{ args: 'secret args' }] },
        },
      });
    });

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(apiFetchMock.mock.calls[0][1].body);

    expect(apiFetchMock.mock.calls[0][0]).toBe('/api/v1/activities/track');
    expect(body).toMatchObject({
      schema: 'agentprovision.macos_app_monitor_event.v1',
      event_id: '11111111-1111-4111-8111-111111111111',
      type: 'app_switch',
      detail_level: 'metadata_only',
      to_app: 'Terminal',
      active_context_id: 'Terminal:abc123',
      source_shell: 'desktop-test-shell',
      window_title_present: true,
      window_title_chars: 24,
    });
    expect(JSON.stringify(body)).not.toContain('secret repo title');
    expect(JSON.stringify(body)).not.toContain('secret args');
    expect(domListener.mock.calls[0][0].detail).toEqual(body);

    window.removeEventListener('luna:activity-event', domListener);
  });

  it('drops malformed native monitor events', async () => {
    renderHook(() => useActivityTracker());

    await waitFor(() => expect(listeners['activity-event']).toBeTruthy());
    await act(async () => {
      listeners['activity-event']({ payload: { type: 'clipboard', value: 'secret' } });
    });

    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
