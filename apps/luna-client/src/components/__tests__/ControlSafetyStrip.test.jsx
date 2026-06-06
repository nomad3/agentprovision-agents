import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

import ControlSafetyStrip, {
  canOpenPermissionSetup,
  labelForAlphaKernelStatus,
  labelForControlMode,
  labelForMacosMonitorStatus,
  labelForPermissionSetupAction,
  labelForPermissionStatus,
  permissionIdentity,
  summarizePermissions,
} from '../ControlSafetyStrip';

beforeEach(() => {
  invokeMock.mockReset();
});

describe('ControlSafetyStrip', () => {
  it('maps control modes to operator labels', () => {
    expect(labelForControlMode('observe')).toBe('Observe');
    expect(labelForControlMode('assist')).toBe('Assist');
    expect(labelForControlMode('control')).toBe('Control');
    expect(labelForControlMode('stopped')).toBe('Stopped');
    expect(labelForControlMode('control_locked')).toBe('Control Locked');
    expect(labelForControlMode('other')).toBe('Control Locked');
  });

  it('summarizes permission readiness without exposing raw values', () => {
    const summary = summarizePermissions({
      screen_recording: { status: 'granted', reason: 'ok' },
      accessibility: { status: 'denied', reason: 'missing' },
      input_monitoring: { status: 'not_required', reason: 'not used' },
      camera: { status: 'unknown', reason: 'deferred' },
      app_identity: {
        bundle_id: 'com.agentprovision.luna',
        code_signature_identifier: 'luna-debug',
      },
    });

    expect(summary.label).toBe('TCC 2/3');
    expect(summary.title).toContain('Screen: granted');
    expect(summary.title).toContain('AX: denied');
    expect(summary.title).toContain('Camera: unknown');
    expect(summary.title).not.toContain('app_identity');
  });

  it('keeps running app identity metadata separate from permission rows', () => {
    const permissions = {
      screen_recording: { status: 'granted', reason: 'ok' },
      app_identity: {
        bundle_id: 'com.agentprovision.luna',
        app_bundle_path: '/Applications/Luna.app',
      },
    };

    expect(permissionIdentity(permissions)).toEqual({
      bundle_id: 'com.agentprovision.luna',
      app_bundle_path: '/Applications/Luna.app',
    });
    expect(summarizePermissions(permissions).label).toBe('TCC 1/1');
  });

  it('maps permission readiness states to operator labels', () => {
    expect(labelForPermissionStatus('granted')).toBe('Granted');
    expect(labelForPermissionStatus('denied')).toBe('Denied');
    expect(labelForPermissionStatus('not_required')).toBe('Not Required');
    expect(labelForPermissionStatus('unknown')).toBe('Unknown');
    expect(canOpenPermissionSetup({ status: 'denied' })).toBe(true);
    expect(canOpenPermissionSetup({ status: 'unknown' })).toBe(true);
    expect(canOpenPermissionSetup({ status: 'granted' })).toBe(false);
    expect(canOpenPermissionSetup({ status: 'not_required' })).toBe(false);
    expect(labelForPermissionSetupAction({ status: 'denied' })).toBe('Enable');
    expect(labelForPermissionSetupAction({ status: 'unknown' })).toBe('Open');
  });

  it('maps local kernel and macOS monitor states to compact labels', () => {
    expect(labelForAlphaKernelStatus('available', true)).toBe('Alpha OK');
    expect(labelForAlphaKernelStatus('missing', false)).toBe('Alpha --');
    expect(labelForMacosMonitorStatus('ready')).toBe('Mac Ready');
    expect(labelForMacosMonitorStatus('denied')).toBe('Mac Denied');
    expect(labelForMacosMonitorStatus('stopped')).toBe('Mac Stopped');
    expect(labelForMacosMonitorStatus('unsupported')).toBe('Mac --');
  });

  it('loads the safety state on mount', async () => {
    invokeMock.mockResolvedValueOnce({
      mode: 'control_locked',
      gesture_state: 'stopped',
      cursor_global: false,
    });

    render(<ControlSafetyStrip />);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('control_get_safety_state');
    });
    expect(screen.getByText('Control Locked')).toBeInTheDocument();
  });

  it('shows disabled assist/control gates before command governance ships', async () => {
    invokeMock.mockResolvedValueOnce({
      mode: 'control_locked',
      can_observe: true,
      can_assist: false,
      can_control: false,
      permissions: {
        screen_recording: { status: 'granted', reason: 'ok' },
        accessibility: { status: 'denied', reason: 'missing' },
      },
    });

    render(<ControlSafetyStrip />);

    expect(await screen.findByRole('button', { name: /^assist$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^control$/i })).toBeDisabled();
    expect(screen.getByText('TCC 1/2')).toBeInTheDocument();
    expect(screen.getByLabelText('Permission readiness TCC 1/2')).toBeInTheDocument();
  });

  it('shows Alpha kernel and macOS monitor readiness without exposing raw window titles', async () => {
    invokeMock.mockResolvedValueOnce({
      mode: 'observe',
      can_observe: true,
      alpha_kernel: {
        status: 'available',
        available: true,
        binary_path: '/opt/homebrew/bin/alpha',
      },
      macos_app_monitor: {
        status: 'ready',
        reason: 'macOS active-app monitoring is ready in metadata-only mode.',
        accessibility_status: 'granted',
        automation_system_events_status: 'unknown',
      },
    });

    render(<ControlSafetyStrip />);

    expect(await screen.findByText('Alpha OK')).toBeInTheDocument();
    expect(screen.getByText('Mac Ready')).toBeInTheDocument();

    fireEvent(window, new CustomEvent('luna:activity-event', {
      detail: {
        schema: 'agentprovision.macos_app_monitor_event.v1',
        event_id: '11111111-1111-4111-8111-111111111111',
        type: 'app_switch',
        to_app: 'Terminal',
        window_title: 'secret repo window title',
        subprocess: { active_processes: [{ args: 'secret args' }] },
      },
    }));

    expect(screen.getByText('Terminal')).toBeInTheDocument();
    expect(screen.queryByText('secret repo window title')).toBeNull();
    expect(screen.queryByText('secret args')).toBeNull();
  });

  it('ignores malformed macOS monitor events before updating the UI', async () => {
    invokeMock.mockResolvedValueOnce({
      mode: 'observe',
      macos_app_monitor: { status: 'ready' },
    });

    render(<ControlSafetyStrip />);

    expect(await screen.findByText('Mac Ready')).toBeInTheDocument();

    fireEvent(window, new CustomEvent('luna:activity-event', {
      detail: {
        type: 'app_switch',
        to_app: 'Terminal',
        window_title: 'secret repo window title',
      },
    }));

    expect(screen.queryByText('Terminal')).toBeNull();
    expect(screen.queryByText('secret repo window title')).toBeNull();
  });

  it('expands permission readiness details from the safety strip', async () => {
    invokeMock.mockResolvedValueOnce({
      mode: 'control_locked',
      can_observe: true,
      permissions: {
        app_identity: {
          bundle_id: 'com.agentprovision.luna',
          app_bundle_path: '/tmp/Luna.app',
          code_signature_identifier: 'luna-debug',
          code_signature_kind: 'ad-hoc',
          permission_scope_note: 'macOS grants TCC permissions to the running app identity.',
        },
        screen_recording: {
          status: 'granted',
          reason: 'macOS Screen Recording preflight is granted.',
          required_for: ['screenshot', 'screen observation'],
        },
        accessibility: {
          status: 'denied',
          reason: 'macOS Accessibility trust preflight is denied or not yet granted.',
          required_for: ['active app', 'pointer control'],
        },
      },
    });

    render(<ControlSafetyStrip />);

    fireEvent.click(await screen.findByRole('button', { name: 'Permission readiness TCC 1/2' }));

    expect(screen.getByLabelText('Permission readiness details')).toBeInTheDocument();
    expect(screen.getByText('Running Luna Identity')).toBeInTheDocument();
    expect(screen.getByText('Bundle: com.agentprovision.luna')).toBeInTheDocument();
    expect(screen.getByText('Signature: ad-hoc | luna-debug')).toBeInTheDocument();
    expect(screen.getByText('App: /tmp/Luna.app')).toBeInTheDocument();
    expect(screen.getByText('Screen')).toBeInTheDocument();
    expect(screen.getByText('Granted')).toBeInTheDocument();
    expect(screen.getByText('AX')).toBeInTheDocument();
    expect(screen.getByText('Denied')).toBeInTheDocument();
    expect(screen.getByText('Required for: active app, pointer control')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enable AX permission' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enable Screen permission' })).toBeNull();
  });

  it('opens the native macOS permission helper from denied TCC rows', async () => {
    invokeMock
      .mockResolvedValueOnce({
        mode: 'control_locked',
        can_observe: true,
        permissions: {
          accessibility: {
            status: 'denied',
            reason: 'macOS Accessibility trust preflight is denied or not yet granted.',
            required_for: ['active app', 'pointer control'],
          },
        },
      })
      .mockResolvedValueOnce({
        mode: 'control_locked',
        can_observe: true,
        permissions: {
          accessibility: {
            status: 'denied',
            reason: 'macOS Accessibility trust preflight is denied or not yet granted.',
            required_for: ['active app', 'pointer control'],
          },
        },
      });

    render(<ControlSafetyStrip />);

    fireEvent.click(await screen.findByRole('button', { name: 'Permission readiness TCC 0/1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Enable AX permission' }));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith(
        'control_open_permission_setup',
        { permission: 'accessibility' },
      );
    });
  });

  it('arms observe-only mode from the local UI', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'control_locked', can_observe: true })
      .mockResolvedValueOnce({ mode: 'observe', gesture_state: 'stopped' });

    render(<ControlSafetyStrip />);

    fireEvent.click(await screen.findByRole('button', { name: /^observe$/i }));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('control_observe_status');
    });
    expect(screen.getByText('Observe', { selector: '.control-safety-label' })).toBeInTheDocument();
  });

  it('stops local capture/control loops from the local UI', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe' })
      .mockResolvedValueOnce({
        mode: 'stopped',
        capture_running: false,
        gesture_state: 'stopped',
        cursor_global: false,
      });

    render(<ControlSafetyStrip />);

    fireEvent.click(await screen.findByRole('button', { name: /^stop$/i }));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('control_stop_all');
    });
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });

  it('locks observation without latching stopped mode', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'observe' })
      .mockResolvedValueOnce({
        mode: 'control_locked',
        can_observe: true,
        gesture_state: 'stopped',
      });

    render(<ControlSafetyStrip />);

    fireEvent.click(await screen.findByRole('button', { name: /^lock$/i }));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('control_lock_all');
    });
    expect(screen.getByText('Control Locked')).toBeInTheDocument();
  });

  it('keeps observe disabled after local stop is latched', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'stopped', can_observe: false });

    render(<ControlSafetyStrip />);

    const observe = await screen.findByRole('button', { name: /^observe$/i });

    expect(observe).toBeDisabled();
    fireEvent.click(observe);
    expect(invokeMock).toHaveBeenCalledTimes(1);
  });

  it('exposes a Resume action to clear a latched Stop (the only escape from stopped)', async () => {
    invokeMock
      .mockResolvedValueOnce({ mode: 'stopped', can_observe: false })
      .mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    render(<ControlSafetyStrip />);

    const resume = await screen.findByRole('button', { name: /^resume$/i });
    expect(resume).toBeEnabled();

    fireEvent.click(resume);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('control_clear_stop');
    });
    expect(screen.getByText('Control Locked')).toBeInTheDocument();
  });

  it('does not show Resume unless Stop is latched', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'control_locked', can_observe: true });

    render(<ControlSafetyStrip />);

    await screen.findByRole('button', { name: /^observe$/i });
    expect(screen.queryByRole('button', { name: /^resume$/i })).toBeNull();
  });

  it('broadcasts native safety state changes for shell presence sync', async () => {
    const handler = vi.fn();
    window.addEventListener('luna:control-safety-changed', handler);
    invokeMock.mockResolvedValueOnce({
      mode: 'stopped',
      can_observe: false,
      gesture_state: 'stopped',
    });

    render(<ControlSafetyStrip />);

    await waitFor(() => {
      expect(handler).toHaveBeenCalled();
    });
    expect(handler.mock.calls.at(-1)[0].detail.mode).toBe('stopped');
    expect(handler.mock.calls.at(-1)[0].detail.can_observe).toBe(false);
    window.removeEventListener('luna:control-safety-changed', handler);
  });
});
