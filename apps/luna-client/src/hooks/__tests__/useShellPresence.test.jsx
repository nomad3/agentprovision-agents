import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const apiFetchMock = vi.fn();
const invokeMock = vi.fn();

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

vi.mock('../../utils/shellIdentity', () => ({
  getOrCreateShellId: () => Promise.resolve('desktop-test-shell'),
}));

vi.mock('../../utils/desktopDeviceEnrollment', () => ({
  enrollDesktopDevice: () => Promise.resolve({
    device_id: 'tenant-desktop-test',
    device_token: 'device-token-test',
    shell_id: 'desktop-test-shell',
  }),
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

function presenceUpdateCalls() {
  return apiFetchMock.mock.calls.filter(([url]) => url === '/api/v1/presence/');
}

function lastRegisteredCapabilities() {
  const call = registerCalls().at(-1);
  return JSON.parse(call[1].body).capabilities;
}

function lastRegisterCall() {
  return registerCalls().at(-1);
}

function captureShellHeartbeatInterval() {
  let heartbeatCallback;
  const originalSetInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, timeout, ...args) => {
    if (timeout === 10000) {
      heartbeatCallback = callback;
    }
    return originalSetInterval(callback, timeout, ...args);
  });
  return () => heartbeatCallback;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  invokeMock.mockReset();
  apiFetchMock.mockResolvedValue({
    json: () => Promise.resolve({ state: 'active' }),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
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
    expect(JSON.parse(lastRegisterCall()[1].body).device_id).toBe('tenant-desktop-test');
    expect(lastRegisterCall()[1].headers['X-Device-Token']).toBe('device-token-test');
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

  it('refreshes full shell registration on heartbeat', async () => {
    invokeMock.mockResolvedValue({ can_observe: true });
    const getHeartbeatCallback = captureShellHeartbeatInterval();

    const { unmount } = renderHook(() => useShellPresence());

    await waitFor(() => expect(registerCalls().length).toBe(1));
    expect(getHeartbeatCallback()).toBeDefined();
    await act(async () => {
      await getHeartbeatCallback()();
    });

    await waitFor(() => expect(registerCalls().length).toBe(2));
    expect(presenceUpdateCalls()).toHaveLength(0);
    expect(JSON.parse(lastRegisterCall()[1].body).device_id).toBe('tenant-desktop-test');
    expect(lastRegisterCall()[1].headers['X-Device-Token']).toBe('device-token-test');

    unmount();
  });

  it('retries full shell registration on heartbeat after an initial failure', async () => {
    invokeMock.mockResolvedValue({ can_observe: true });
    apiFetchMock
      .mockRejectedValueOnce(new Error('temporary outage'))
      .mockResolvedValue({
        json: () => Promise.resolve({ state: 'active' }),
      });
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const getHeartbeatCallback = captureShellHeartbeatInterval();

    const { unmount } = renderHook(() => useShellPresence());

    await waitFor(() => expect(registerCalls().length).toBe(1));
    expect(getHeartbeatCallback()).toBeDefined();
    await act(async () => {
      await getHeartbeatCallback()();
    });

    await waitFor(() => expect(registerCalls().length).toBe(2));
    expect(JSON.parse(lastRegisterCall()[1].body).device_id).toBe('tenant-desktop-test');
    expect(lastRegisterCall()[1].headers['X-Device-Token']).toBe('device-token-test');

    unmount();
  });
});
