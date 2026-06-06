const SHELL_STORAGE_KEY = 'luna_shell_id';
const SHELL_TYPE = 'desktop';

function rememberShellId(id) {
  try {
    localStorage.setItem(SHELL_STORAGE_KEY, id);
  } catch {}
  try {
    sessionStorage.setItem(SHELL_STORAGE_KEY, id);
  } catch {}
}

export function getCachedShellId() {
  try {
    return localStorage.getItem(SHELL_STORAGE_KEY) || sessionStorage.getItem(SHELL_STORAGE_KEY);
  } catch {
    return null;
  }
}

function createFallbackShellId() {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${SHELL_TYPE}-${suffix}`;
}

function isDesktopShellId(id) {
  return typeof id === 'string' && id.startsWith(`${SHELL_TYPE}-`) && id.length > SHELL_TYPE.length + 1;
}

export async function getOrCreateShellId() {
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const shellId = await invoke('get_or_create_shell_id');
    if (isDesktopShellId(shellId)) {
      rememberShellId(shellId);
      return shellId;
    }
  } catch {
    // Browser/PWA/test fallback.
  }

  let shellId = getCachedShellId();
  if (!isDesktopShellId(shellId)) {
    shellId = createFallbackShellId();
  }
  rememberShellId(shellId);
  return shellId;
}
