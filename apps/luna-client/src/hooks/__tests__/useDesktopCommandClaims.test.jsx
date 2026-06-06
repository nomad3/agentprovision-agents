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

const SESSION_ID = '33333333-3333-3333-3333-333333333333';
const SHELL_ID = 'desktop-44444444-4444-4444-4444-444444444444';
const DEVICE_ID = '88888888-8888-8888-8888-888888888888';
const COMMAND_ID = '99999999-9999-9999-9999-999999999999';
const DEFAULT_ENVELOPE_NONCE = 'envelope-nonce-test';

const CAPABILITY_BY_ACTION = {
  capture_screenshot: 'screenshot',
  get_active_app: 'active_app',
  read_clipboard: 'clipboard_read',
  pointer_move: 'pointer_control',
  pointer_click: 'pointer_control',
  keyboard_type: 'keyboard_control',
  keyboard_key_chord: 'keyboard_control',
};

function validEnvelope(action, overrides = {}) {
  return {
    schema: 'agentprovision.desktop_command_envelope.v1',
    signed: true,
    signature_alg: 'HMAC-SHA256',
    key_id: 'agentprovision-desktop-command-hmac-v1',
    policy_version: 1,
    issuer: 'agentprovision-api',
    tenant_id: '11111111-1111-1111-1111-111111111111',
    user_id: '22222222-2222-2222-2222-222222222222',
    session_id: SESSION_ID,
    desktop_command_id: COMMAND_ID,
    shell_id: SHELL_ID,
    device_id: DEVICE_ID,
    action,
    capability: CAPABILITY_BY_ACTION[action],
    mode: 'observe',
    risk_tier: action?.startsWith('pointer') || action?.startsWith('keyboard')
      ? 'native_control'
      : 'observe',
    policy_decision: 'lease_claimed',
    nonce: DEFAULT_ENVELOPE_NONCE,
    issued_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    expires_at_ms: Date.now() + 60_000,
    signature: 'valid-test-signature',
    ...overrides,
  };
}

function claimedCommand(action = 'capture_screenshot', envelopeOverrides = {}) {
  const payload = { action, mode: 'observe' };
  if (envelopeOverrides !== null) {
    payload.command_envelope = validEnvelope(action, envelopeOverrides);
  }
  return {
    desktop_command_id: COMMAND_ID,
    session_id: SESSION_ID,
    status: 'claimed',
    shell_id: SHELL_ID,
    device_id: DEVICE_ID,
    capability: CAPABILITY_BY_ACTION[action],
    payload,
  };
}

function withEnvelope(metadata = {}, nonce = DEFAULT_ENVELOPE_NONCE) {
  return { ...metadata, envelope_nonce: nonce };
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
      .mockResolvedValueOnce('raw-screenshot-base64-must-not-forward')
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true });

    await executeClaimedDesktopCommand(
      claimedCommand('capture_screenshot'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('capture_screenshot');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('succeeded');
    expect(body.metadata).toEqual(withEnvelope({
      result_kind: 'binary',
      result_size_bytes: 29,
    }));
    expect(JSON.stringify(body)).not.toContain('raw-screenshot-base64-must-not-forward');
  });

  it('preempts observe commands if Stop is latched after native execution returns', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true })
      .mockResolvedValueOnce({ app: 'Sensitive App', title_present: true, title_chars: 15 })
      .mockResolvedValueOnce({ mode: 'stopped', can_observe: false });

    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('get_active_app');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('preempted');
    expect(body.reason).toBe('desktop control stopped; get_active_app preempted');
    expect(body.metadata).toEqual(withEnvelope({ control_mode: 'stopped' }));
    expect(JSON.stringify(body)).not.toContain('Sensitive App');
    expect(JSON.stringify(body)).not.toContain('Sensitive Title');
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

  it('forwards the signed envelope nonce on completion when claim includes one', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    await executeClaimedDesktopCommand(
      claimedCommand('read_clipboard', { nonce: 'custom-envelope-nonce-test' }),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.metadata).toEqual({
      control_mode: 'control_locked',
      can_observe: true,
      envelope_nonce: 'custom-envelope-nonce-test',
    });
  });

  it('denies malformed claimed envelopes before native invocation', async () => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', null),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope missing');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });

  it('denies expired claimed envelopes before native invocation', async () => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', {
        expires_at: new Date(Date.now() - 60_000).toISOString(),
        expires_at_ms: Date.now() - 60_000,
      }),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope expired');
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
  });

  it('denies claimed envelopes with a missing nonce before native invocation', async () => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', { nonce: '' }),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope nonce missing');
    expect(body.metadata).toEqual({ result_kind: 'error' });
  });

  it('denies claimed envelopes without signature metadata before native invocation', async () => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', { signature: '' }),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope signature invalid');
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
  });

  it('denies claimed envelopes bound to another session before native invocation', async () => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', {
        session_id: '33333333-3333-3333-3333-333333333334',
      }),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
      {},
      { sessionId: '33333333-3333-3333-3333-333333333333' },
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope binding mismatch');
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
  });

  it.each([
    ['command id', { desktop_command_id: '99999999-9999-9999-9999-999999999998' }],
    ['shell id', { shell_id: 'desktop-55555555-5555-5555-5555-555555555555' }],
    ['device id', { device_id: '88888888-8888-8888-8888-888888888887' }],
    ['action', { action: 'read_clipboard' }],
    ['capability', { capability: 'clipboard_read' }],
  ])('denies claimed envelopes with a mismatched %s before native invocation', async (_label, override) => {
    await executeClaimedDesktopCommand(
      claimedCommand('get_active_app', override),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
      {},
      { sessionId: '33333333-3333-3333-3333-333333333333' },
    );

    expect(invokeMock).not.toHaveBeenCalled();
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop command envelope binding mismatch');
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
  });

  it('denies native control commands without invoking local pointer or keyboard controls', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'control_locked', can_control: false });

    await executeClaimedDesktopCommand(
      claimedCommand('pointer_click'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    expect(invokeMock).not.toHaveBeenCalledWith('control_pointer_click');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('denied');
    expect(body.reason).toBe('desktop native control disabled; pointer_click denied');
    expect(body.metadata).toEqual(withEnvelope({
      control_mode: 'control_locked',
      result_kind: 'unsupported',
    }));
  });

  it('preempts native control commands when local Stop is latched', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'stopped', can_control: false });

    await executeClaimedDesktopCommand(
      claimedCommand('keyboard_type'),
      'desktop-44444444-4444-4444-4444-444444444444',
      'device-token-test',
      invokeMock,
    );

    expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    expect(invokeMock).not.toHaveBeenCalledWith('control_keyboard_type');
    const body = JSON.parse(completeCalls()[0][1].body);
    expect(body.status).toBe('preempted');
    expect(body.reason).toBe('desktop control stopped; keyboard_type preempted');
    expect(body.metadata).toEqual(withEnvelope({ control_mode: 'stopped' }));
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
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
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
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
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
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
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
      .mockResolvedValueOnce({ app: 'Sensitive App', title_present: true, title_chars: 15 })
      .mockResolvedValueOnce({ mode: 'observe', can_observe: true });

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
    expect(completeBody.metadata).toEqual(withEnvelope({
      result_kind: 'json',
      result_fields: ['app', 'title_chars', 'title_present'],
    }));
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
    expect(body.metadata).toEqual(withEnvelope({ result_kind: 'error' }));
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
