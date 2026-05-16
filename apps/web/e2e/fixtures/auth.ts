/*
 * Auth fixture helpers shared by every dashboard spec.
 *
 * The actual login happens once in `auth.setup.ts`. This module just
 * exposes a typed `test` object plus a couple of convenience helpers
 * for specs that need to assert against the persisted auth state.
 */
import { test as base, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

export const STORAGE_STATE_PATH = path.resolve(__dirname, '..', '.auth', 'saguilera.json');

/**
 * Returns true if the e2e storage state file exists. Useful for
 * fast-failing with a clear error message instead of letting the
 * browser context load an empty state and then 401 against every API.
 */
export function hasStorageState(): boolean {
  try {
    return fs.statSync(STORAGE_STATE_PATH).isFile();
  } catch {
    return false;
  }
}

/**
 * Extracts the JWT from a persisted storage state file (without
 * touching the page). The web app stores the entire user blob under
 * `localStorage.user`; we read it back here for assertions/debugging.
 */
export function readStoredJwt(): string | null {
  if (!hasStorageState()) return null;
  try {
    const raw = fs.readFileSync(STORAGE_STATE_PATH, 'utf8');
    const state = JSON.parse(raw);
    const origins = state?.origins || [];
    for (const origin of origins) {
      for (const item of origin.localStorage || []) {
        if (item.name === 'user') {
          const parsed = JSON.parse(item.value);
          return parsed?.access_token || null;
        }
      }
    }
  } catch {
    /* fall through */
  }
  return null;
}

// Re-export base `test`/`expect` for spec convenience. Keeps imports
// in spec files short: `import { test, expect } from '../fixtures/auth';`
export const test = base;
export { expect };
