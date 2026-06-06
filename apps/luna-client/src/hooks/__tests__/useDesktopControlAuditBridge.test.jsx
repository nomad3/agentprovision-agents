import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const apiFetchMock = vi.fn();
let auditListener;
const unlistenMock = vi.fn();

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn((eventName, callback) => {
    if (eventName === 'desktop-control-audit') auditListener = callback;
    return Promise.resolve(unlistenMock);
  }),
}));

import { safeAuditBody, useDesktopControlAuditBridge } from '../useDesktopControlAuditBridge';

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue({});
  auditListener = undefined;
  unlistenMock.mockReset();
});

describe('useDesktopControlAuditBridge', () => {
  it('builds an allow-listed metadata-only payload', () => {
    const body = safeAuditBody({
      payload: {
        event_id: '55555555-5555-5555-5555-555555555555',
        event_type: 'desktop_observation_denied',
        source: 'tauri_local',
        action: 'capture_screenshot',
        capability: 'screenshot',
        outcome: 'denied',
        reason: 'screen recording denied',
        mode: 'observe',
        created_at_ms: 123,
        screen_recording_status: 'denied',
        accessibility_status: 'granted',
        automation_system_events_status: 'unknown',
        raw_clipboard_text: 'must not forward',
        screenshot_base64: 'must not forward',
      },
    }, 'session-1', 'desktop-44444444-4444-4444-4444-444444444444');

    expect(body).toEqual({
      session_id: 'session-1',
      shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
      event_id: '55555555-5555-5555-5555-555555555555',
      event_type: 'desktop_observation_denied',
      source: 'tauri_local',
      action: 'capture_screenshot',
      capability: 'screenshot',
      outcome: 'denied',
      reason: 'screen recording denied',
      mode: 'observe',
      created_at_ms: 123,
      screen_recording_status: 'denied',
      accessibility_status: 'granted',
      automation_system_events_status: 'unknown',
    });
    expect(JSON.stringify(body)).not.toContain('must not forward');
  });

  it('posts native audit events with the active session and shell id', async () => {
    renderHook(() => useDesktopControlAuditBridge(
      '33333333-3333-3333-3333-333333333333',
      'desktop-44444444-4444-4444-4444-444444444444',
    ));

    await waitFor(() => expect(auditListener).toBeTypeOf('function'));

    await act(async () => {
      await auditListener({
        payload: {
          event_id: '55555555-5555-5555-5555-555555555555',
          event_type: 'desktop_observation_denied',
          source: 'tauri_local',
          action: 'capture_screenshot',
          capability: 'screenshot',
          outcome: 'denied',
          mode: 'observe',
          screen_recording_status: 'denied',
        },
      });
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/desktop-control/events/local-observation', {
      method: 'POST',
      body: JSON.stringify({
        session_id: '33333333-3333-3333-3333-333333333333',
        shell_id: 'desktop-44444444-4444-4444-4444-444444444444',
        event_id: '55555555-5555-5555-5555-555555555555',
        event_type: 'desktop_observation_denied',
        source: 'tauri_local',
        action: 'capture_screenshot',
        capability: 'screenshot',
        outcome: 'denied',
        reason: null,
        mode: 'observe',
        created_at_ms: null,
        screen_recording_status: 'denied',
        accessibility_status: null,
        automation_system_events_status: null,
      }),
    });
  });

  it('ignores a native payload shell id override', () => {
    const body = safeAuditBody({
      payload: {
        shell_id: 'desktop-99999999-9999-9999-9999-999999999999',
        event_id: '55555555-5555-5555-5555-555555555555',
        event_type: 'desktop_observation_denied',
        source: 'tauri_local',
        action: 'capture_screenshot',
        capability: 'screenshot',
        outcome: 'denied',
        mode: 'observe',
      },
    }, '33333333-3333-3333-3333-333333333333', 'desktop-44444444-4444-4444-4444-444444444444');

    expect(body.shell_id).toBe('desktop-44444444-4444-4444-4444-444444444444');
  });

  it('does not subscribe before session and shell are known', async () => {
    renderHook(() => useDesktopControlAuditBridge(null, 'desktop-shell'));

    await Promise.resolve();

    expect(auditListener).toBeUndefined();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
