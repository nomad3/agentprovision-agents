import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

import ControlSafetyStrip, { labelForControlMode } from '../ControlSafetyStrip';

beforeEach(() => {
  invokeMock.mockReset();
});

describe('ControlSafetyStrip', () => {
  it('maps control modes to operator labels', () => {
    expect(labelForControlMode('observe')).toBe('Observe');
    expect(labelForControlMode('stopped')).toBe('Stopped');
    expect(labelForControlMode('control_locked')).toBe('Control Locked');
    expect(labelForControlMode('other')).toBe('Control Locked');
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

  it('keeps observe disabled after local stop is latched', async () => {
    invokeMock.mockResolvedValueOnce({ mode: 'stopped', can_observe: false });

    render(<ControlSafetyStrip />);

    const observe = await screen.findByRole('button', { name: /^observe$/i });

    expect(observe).toBeDisabled();
    fireEvent.click(observe);
    expect(invokeMock).toHaveBeenCalledTimes(1);
  });
});
