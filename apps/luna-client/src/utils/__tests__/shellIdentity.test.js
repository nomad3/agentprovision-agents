import { describe, it, expect, vi, beforeEach } from 'vitest';

const invokeMock = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args) => invokeMock(...args),
}));

import { getCachedShellId, getOrCreateShellId } from '../shellIdentity';

beforeEach(() => {
  invokeMock.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});

describe('shellIdentity', () => {
  it('uses and caches the durable Tauri shell id when available', async () => {
    invokeMock.mockResolvedValueOnce('desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4');

    const shellId = await getOrCreateShellId();

    expect(invokeMock).toHaveBeenCalledWith('get_or_create_shell_id');
    expect(shellId).toBe('desktop-6558cd2d-fbf9-4c74-879f-25f93ffc36f4');
    expect(getCachedShellId()).toBe(shellId);
  });

  it('falls back to a stable browser shell id when Tauri is unavailable', async () => {
    invokeMock.mockRejectedValue(new Error('not in tauri'));

    const first = await getOrCreateShellId();
    const second = await getOrCreateShellId();

    expect(first).toMatch(/^desktop-/);
    expect(second).toBe(first);
    expect(getCachedShellId()).toBe(first);
  });
});
