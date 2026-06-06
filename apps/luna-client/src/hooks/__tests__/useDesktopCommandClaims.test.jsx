import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const apiFetchMock = vi.fn();
const enrollDesktopDeviceMock = vi.fn();
const invokeMock = vi.fn();
const unlistenMock = vi.fn();
let safetyListener;

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

vi.mock('../../utils/desktopDeviceEnrollment', () => ({
  enrollDesktopDevice: (...args) => enrollDesktopDeviceMock(...args),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn((eventName, callback) => {
    if (eventName === 'control-safety-changed') safetyListener = callback;
    return Promise.resolve(unlistenMock);
  }),
}));

import {
  executeClaimedDesktopCommand,
  useDesktopCommandClaims,
} from '../useDesktopCommandClaims';

function claimedCommand(action = 'capture_screenshot') {
  return {
    desktop_command_id: '99999999-9999-9999-9999-999999999999',
    status: 'claimed',
    shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
    payload: { action, mode: 'observe' },
  };
}

function jsonResponse(body) {
  return {
    json: () => Promise.resolve(body),
  };
}

function completeCalls() {
  return apiFetchMock.mock.calls.filter(([url]) => url.includes('/complete'));
}

beforeEach(() => {
  apiFetchMock.mockReset();
  enrollDesktopDeviceMock.mockReset();
  invokeMock.mockReset();
  unlistenMock.mockReset();
  safetyListener = undefined;
  enrollDesktopDeviceMock.mockResolvedValue({
    device_id: 'tenant-desktop-test',
    device_token: 'device-token-test',
    shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
  });
  apiFetchMock.mockResolvedValue(jsonResponse({}));
});

describe('executeClaimedDesktopCommand', () => {
  it('executes observe commands but completes with metadata-only results', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockResolvedValueOnce('raw-screenshot-base64-must-not-forward');

    await executeClaimedDesktopCommand(
      claimedCommand('capture_screenshot'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('capture_screenshot');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('succeeded');
    expect(body.metadata).toEqual({
      result_kind: 'binary',
      result_size_bytes: 29,
    });
    expect(JSON.stringify(body)).not.toContain('raw-screenshot-base64-must-not-forward');
  });

  it('denies claimed commands while observe mode is locked', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    await executeClaimedDesktopCommand(
      claimedCommand('read_clipboard'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).not.toHaveBeenCalledWith('read_clipboard');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toContain('desktop observe locked');
  });

  it('completes claimed commands as failed when safety state is unavailable', async () => {
    invokeMock.mockRejectedValueOnce(new Error('native safety unavailable'));

    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    expect(invokeMock).not.toHaveBeenCalledWith('get_active_app');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('failed');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });

  it('retries terminal completion before letting executor errors escape', async () => {
    apiFetchMock
      .mockRejectedValueOnce(new Error('temporary completion failure'))
      .mockResolvedValueOnce(jsonResponse({}));
    invokeMock.mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
      { completeRetryDelayMs: 0 },
    );

    expect(completeCalls()).toHaveLength(2);
    const body = JSON.parse(completeCalls()[1][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toContain('desktop observe locked');
  });

  it('completes claimed commands as failed when safety state hangs', async () => {
    invokeMock.mockReturnValueOnce(new Promise(() => {}));

    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
      { safetyTimeoutMs: 5 },
    );

    expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    expect(invokeMock).not.toHaveBeenCalledWith('get_active_app');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('failed');
    expect(body.reason).toContain('timed out');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });

  it('completes claimed commands as failed when a native observe command hangs', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockReturnValueOnce(new Promise(() => {}));

    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
      { nativeTimeoutMs: 5 },
    );

    expect(invokeMock).toHaveBeenCalledWith('get_active_app');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('failed');
    expect(body.reason).toContain('timed out');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });
});

describe('useDesktopCommandClaims', () => {
  it('claims one command with the enrolled desktop device token', async () => {
    apiFetchMock.mockImplementation((url) => {
      if (url === '/api/v1/desktop-control/commands/claim') {
        return Promise.resolve(jsonResponse({
          status: 'claimed',
          command: claimedCommand('get_active_app'),
        }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockResolvedValueOnce({ app: 'Sensitive App', title: 'Sensitive Title' });

    renderHook(() => useDesktopCommandClaims(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
    ));

    await waitFor(() => expect(completeCalls().length).toBe(1));
    const claimCall = apiFetchMock.mock.calls.find(
      ([url]) => url === '/api/v1/desktop-control/commands/claim',
    );
    expect(claimCall[1].headers['X-Device-Token']).toBe('device-token-test');
    expect(JSON.parse(claimCall[1].body)).toEqual({
      session_id: '33333333-3333-3333-3333-333333333333',
      shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
      lease_seconds: 30,
    });
    const completeBody = JSON.parse(completeCalls()[0][1].body);
    expect(completeBody.metadata).toEqual({
      result_kind: 'json',
      result_fields: ['app', 'title'],
    });
    expect(JSON.stringify(completeBody)).not.toContain('Sensitive App');
    expect(JSON.stringify(completeBody)).not.toContain('Sensitive Title');
  });

  it('completes a claimed command instead of waiting for backend lease expiry when native observe hangs', async () => {
    apiFetchMock.mockImplementation((url) => {
      if (url === '/api/v1/desktop-control/commands/claim') {
        return Promise.resolve(jsonResponse({
          status: 'claimed',
          command: claimedCommand('get_active_app'),
        }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockReturnValueOnce(new Promise(() => {}));

    renderHook(() => useDesktopCommandClaims(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
      { timeouts: { nativeTimeoutMs: 5 } },
    ));

    await waitFor(() => expect(completeCalls().length).toBe(1));
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('failed');
    expect(body.reason).toContain('timed out');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });

  it('denies a claimed command through the hook while observe mode is locked', async () => {
    apiFetchMock.mockImplementation((url) => {
      if (url === '/api/v1/desktop-control/commands/claim') {
        return Promise.resolve(jsonResponse({
          status: 'claimed',
          command: claimedCommand('read_clipboard'),
        }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    invokeMock
      .mockResolvedValueOnce({ mode: 'control_locked', can_observe: true })
      .mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    renderHook(() => useDesktopCommandClaims(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
    ));

    await waitFor(() => expect(completeCalls().length).toBe(1));
    expect(invokeMock).not.toHaveBeenCalledWith('read_clipboard');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toContain('desktop observe locked');
  });

  it('preempts a claimed command if the hook is cancelled before execution', async () => {
    let resolveClaim;
    apiFetchMock.mockImplementation((url) => {
      if (url === '/api/v1/desktop-control/commands/claim') {
        return Promise.resolve({
          json: () => new Promise((resolve) => {
            resolveClaim = () => resolve({
              status: 'claimed',
              command: claimedCommand('get_active_app'),
            });
          }),
        });
      }
      return Promise.resolve(jsonResponse({}));
    });
    invokeMock.mockResolvedValueOnce({ mode: 'observe', can_observe: true });

    const { unmount } = renderHook(() => useDesktopCommandClaims(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
    ));

    await waitFor(() => expect(resolveClaim).toBeTypeOf('function'));
    unmount();
    await act(async () => {
      resolveClaim();
    });

    await waitFor(() => expect(completeCalls().length).toBe(1));
    expect(invokeMock).not.toHaveBeenCalledWith('get_active_app');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('preempted');
    expect(body.reason).toContain('cancelled before execution');
  });

  it('preempts session commands when local Stop is latched', async () => {
    apiFetchMock.mockImplementation((url) => {
      if (url === '/api/v1/desktop-control/commands/claim') {
        return Promise.resolve(jsonResponse({ status: 'empty', command: null }));
      }
      return Promise.resolve(jsonResponse({}));
    });

    renderHook(() => useDesktopCommandClaims(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
    ));

    await waitFor(() => expect(safetyListener).toBeTypeOf('function'));
    await act(async () => {
      await safetyListener({ payload: { mode: 'stopped' } });
    });

    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some(
        ([url]) => url === '/api/v1/desktop-control/commands/stop',
      )).toBe(true);
    });
    const stopCall = apiFetchMock.mock.calls.find(
      ([url]) => url === '/api/v1/desktop-control/commands/stop',
    );
    expect(stopCall[1].headers['X-Device-Token']).toBe('device-token-test');
    expect(JSON.parse(stopCall[1].body)).toEqual({
      session_id: '33333333-3333-3333-3333-333333333333',
      shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
      reason: 'local Stop latched',
    });
  });
});
