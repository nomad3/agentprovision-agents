import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const apiFetchMock = vi.fn();
const invokeMock = vi.fn();

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

vi.mock('../../utils/shellIdentity', () => ({
  getOrCreateShellId: () => Promise.resolve('desktop-test-shell'),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(() => Promise.resolve(vi.fn())),
}));

import { useShellPresence } from '../useShellPresence';

function registerCalls() {
  return apiFetchMock.mock.calls.filter(([url]) => url === '/api/v1/presence/shell/register');
}

function lastRegisteredCapabilities() {
  const call = registerCalls().at(-1);
  return JSON.parse(call[1].body).capabilities;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  invokeMock.mockReset();
  apiFetchMock.mockResolvedValue({
    json: () => Promise.resolve({ state: 'active' }),
  });
});

describe('useShellPresence', () => {
  it('registers capabilities from native control safety state', async () => {
    invokeMock.mockResolvedValueOnce({
      can_observe: false,
      can_control_pointer: false,
      can_control_keyboard: false,
    });

    renderHook(() => useShellPresence());

    await waitFor(() => expect(registerCalls().length).toBe(1));
    expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    expect(lastRegisteredCapabilities()).toMatchObject({
      can_observe: false,
      can_stop: true,
      can_control_pointer: false,
      can_control_keyboard: false,
    });
  });

  it('re-registers when local safety state changes', async () => {
    invokeMock
      .mockResolvedValueOnce({ can_observe: true })
      .mockResolvedValueOnce({ can_observe: false });

    renderHook(() => useShellPresence());

    await waitFor(() => expect(registerCalls().length).toBe(1));
    await act(async () => {
      window.dispatchEvent(new CustomEvent('luna:control-safety-changed'));
    });

    await waitFor(() => expect(registerCalls().length).toBe(2));
    expect(lastRegisteredCapabilities().can_observe).toBe(false);
  });
});
