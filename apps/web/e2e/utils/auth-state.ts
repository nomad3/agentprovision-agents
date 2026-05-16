/*
 * Convenience reader for the persisted Playwright storage-state file.
 *
 * Specs occasionally need to know who's logged in (e.g. the file-tree
 * spec wants to assert the platform-scope tab is visible only for
 * superusers). Rather than re-decoding the JWT in every spec, we
 * expose a single helper that returns the parsed user blob.
 */
import fs from 'fs';
import { STORAGE_STATE_PATH } from '../fixtures/auth';

export interface StoredUser {
  access_token?: string;
  token_type?: string;
  user_id?: string;
  email?: string;
  is_superuser?: boolean;
  tenant_id?: string;
  [key: string]: unknown;
}

/**
 * Reads the persisted auth state file and returns the parsed `user`
 * localStorage entry. Returns null if the file is missing or
 * malformed — callers should treat that as "not logged in".
 */
export function readStoredUser(): StoredUser | null {
  try {
    const raw = fs.readFileSync(STORAGE_STATE_PATH, 'utf8');
    const state = JSON.parse(raw);
    const origins = state?.origins || [];
    for (const origin of origins) {
      for (const item of origin.localStorage || []) {
        if (item.name === 'user') {
          return JSON.parse(item.value) as StoredUser;
        }
      }
    }
  } catch {
    /* fall through to null */
  }
  return null;
}

/**
 * Decodes the JWT payload from the persisted user blob without
 * verifying signatures (we trust the file we wrote ourselves). Used
 * to read superuser/tenant claims that the React app may surface
 * differently than the raw login response.
 */
export function decodeJwtClaims(): Record<string, unknown> | null {
  const user = readStoredUser();
  const token = user?.access_token;
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length < 2) return null;
  try {
    // Base64URL → Base64 → JSON. Node's Buffer handles padding
    // forgivingly so we don't need to repad manually.
    const json = Buffer.from(parts[1].replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
    return JSON.parse(json);
  } catch {
    return null;
  }
}

/**
 * True if the persisted user is a superuser (platform-scope features
 * key off this). Reads both the explicit `is_superuser` flag and the
 * JWT claim for safety — the login response and the JWT can drift
 * during migrations.
 */
export function isSuperuser(): boolean {
  const user = readStoredUser();
  if (user?.is_superuser) return true;
  const claims = decodeJwtClaims();
  return !!(claims && (claims.is_superuser === true || claims.role === 'superuser'));
}
