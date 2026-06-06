import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

import ControlSafetyStrip, { labelForControlMode, summarizePermissions } from '../ControlSafetyStrip';

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
    });

    expect(summary.label).toBe('TCC 2/3');
    expect(summary.title).toContain('Screen: granted');
    expect(summary.title).toContain('AX: denied');
    expect(summary.title).toContain('Camera: unknown');
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
