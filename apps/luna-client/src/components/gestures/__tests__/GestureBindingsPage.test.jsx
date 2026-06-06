import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

vi.mock('../../../hooks/useGestureBindings', () => ({
  useGestureBindings: () => ({
    bindings: [],
    loaded: true,
    error: null,
    detectConflict: vi.fn(),
    upsert: vi.fn(),
    remove: vi.fn(),
    resetToDefaults: vi.fn(),
  }),
}));

vi.mock('../../../hooks/useGesture', () => ({
  useGesture: () => ({
    wakeState: 'sleeping',
    status: { state: 'stopped' },
  }),
}));

vi.mock('../GestureBindingRow', () => ({
  default: () => <div data-testid="binding-row" />,
}));

vi.mock('../GestureRecorder', () => ({
  default: () => <div data-testid="gesture-recorder" />,
}));

import GestureBindingsPage from '../GestureBindingsPage';

beforeEach(() => {
  invokeMock.mockReset();
});

describe('GestureBindingsPage', () => {
  it('starts the gesture engine when settings owns the gesture lifecycle', async () => {
    invokeMock.mockResolvedValue(null);

    render(<GestureBindingsPage />);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('gesture_start', undefined);
    });
    expect(invokeMock).toHaveBeenCalledWith('gesture_check_accessibility', undefined);
    expect(invokeMock).toHaveBeenCalledWith('gesture_get_cursor_global', undefined);
  });

  it('retries gesture start when observe mode is enabled after an initial lock denial', async () => {
    let gestureStartCalls = 0;
    invokeMock.mockImplementation((command) => {
      if (command === 'gesture_start') {
        gestureStartCalls += 1;
        return gestureStartCalls === 1
          ? Promise.reject(new Error('desktop observe locked'))
          : Promise.resolve(null);
      }
      return Promise.resolve(null);
    });

    render(<GestureBindingsPage />);

    await waitFor(() => {
      expect(gestureStartCalls).toBe(1);
    });

    window.dispatchEvent(new CustomEvent('luna:control-safety-changed', {
      detail: { mode: 'observe' },
    }));

    await waitFor(() => {
      expect(gestureStartCalls).toBe(2);
    });
  });
});
