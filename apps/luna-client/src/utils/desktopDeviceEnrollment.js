import { apiFetch } from '../api';

const DESKTOP_DEVICE_STORAGE_PREFIX = 'luna_desktop_device:';

function storageKey(shellId) {
  return `${DESKTOP_DEVICE_STORAGE_PREFIX}${shellId}`;
}

function readCachedEnrollment(shellId) {
  try {
    const raw = localStorage.getItem(storageKey(shellId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      parsed?.shell_id === shellId
      && typeof parsed.device_id === 'string'
      && typeof parsed.device_token === 'string'
    ) {
      return parsed;
    }
  } catch {}
  return null;
}

function rememberEnrollment(shellId, enrollment) {
  try {
    localStorage.setItem(storageKey(shellId), JSON.stringify(enrollment));
  } catch {}
}

export async function enrollDesktopDevice(shellId, capabilities = {}) {
  const cached = readCachedEnrollment(shellId);
  if (cached) return cached;

  const response = await apiFetch('/api/v1/devices/desktop/enroll', {
    method: 'POST',
    body: JSON.stringify({
      shell_id: shellId,
      capabilities,
      app_version: import.meta.env.VITE_LUNA_APP_VERSION || null,
    }),
  });
  const enrollment = await response.json();
  rememberEnrollment(shellId, enrollment);
  return enrollment;
}

export function forgetDesktopDeviceEnrollment(shellId) {
  try {
    localStorage.removeItem(storageKey(shellId));
  } catch {}
}
