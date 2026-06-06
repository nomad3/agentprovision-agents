import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

vi.mock('../../../hooks/useGesture', () => ({
  useGesture: () => ({
    wakeState: 'sleeping',
    status: { state: 'stopped' },
  }),
}));

import GestureCalibration from '../GestureCalibration';

beforeEach(() => {
  invokeMock.mockReset();
});

describe('GestureCalibration', () => {
  it('starts the gesture engine when calibration owns the camera lifecycle', async () => {
    invokeMock.mockImplementation((command) => {
      if (command === 'gesture_list_cameras') return Promise.resolve(['FaceTime']);
      return Promise.resolve(null);
    });

    render(<GestureCalibration />);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('gesture_start');
    });
    expect(invokeMock).toHaveBeenCalledWith('gesture_list_cameras');
  });
});
