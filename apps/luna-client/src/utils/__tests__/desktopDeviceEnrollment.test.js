import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiFetchMock = vi.fn();

vi.mock('../../api', () => ({
  apiFetch: (...args) => apiFetchMock(...args),
}));

import { enrollDesktopDevice, forgetDesktopDeviceEnrollment } from '../desktopDeviceEnrollment';

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
});

describe('desktopDeviceEnrollment', () => {
  it('enrolls once and reuses the cached desktop device token for a shell', async () => {
    apiFetchMock.mockResolvedValueOnce({
      json: () => Promise.resolve({
        id: 'device-row-id',
        device_id: 'tenant-desktop-shell',
        device_token: 'token-1',
        shell_id: 'desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4',
      }),
    });

    const first = await enrollDesktopDevice(
      'desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4',
      { can_observe: true },
    );
    const second = await enrollDesktopDevice(
      'desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4',
      { can_observe: false },
    );

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock.mock.calls[0][0]).toBe('/api/v1/devices/desktop/enroll');
    expect(JSON.parse(apiFetchMock.mock.calls[0][1].body)).toMatchObject({
      shell_id: 'desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4',
      capabilities: { can_observe: true },
    });
    expect(first.device_token).toBe('token-1');
    expect(second.device_token).toBe('token-1');

    forgetDesktopDeviceEnrollment('desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4');
    apiFetchMock.mockResolvedValueOnce({
      json: () => Promise.resolve({
        id: 'device-row-id',
        device_id: 'tenant-desktop-shell',
        device_token: 'token-2',
        shell_id: 'desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4',
      }),
    });
    await enrollDesktopDevice('desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4');
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
  });
});
