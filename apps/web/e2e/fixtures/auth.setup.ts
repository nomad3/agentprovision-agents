/*
 * One-shot login fixture.
 *
 * Runs in its own Playwright project (`setup`) and persists the
 * authenticated browser context to `e2e/.auth/saguilera.json`. Every
 * other spec depends on this project so they boot into the app
 * already-logged-in.
 *
 * The login form lives at `/login` (apps/web/src/pages/LoginPage.js)
 * and posts email/password to the API. On success the React app
 * writes the JWT + user blob into `localStorage.user` and the
 * AuthContext takes over. Playwright's storageState capture includes
 * localStorage, so persisting after a successful login is enough —
 * subsequent specs hydrate auth from `localStorage.user` on mount.
 *
 * Credentials are read from env (`E2E_USER_EMAIL` / `E2E_USER_PASSWORD`).
 * The `.env.test.local` file at apps/web/ is the convention; see
 * playwright.config.ts for the loader.
 */
import { test as setup, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const STORAGE_STATE = path.resolve(__dirname, '..', '.auth', 'saguilera.json');

setup('authenticate', async ({ page }) => {
  const email = process.env.E2E_USER_EMAIL || 'saguilera1608@gmail.com';
  const password = process.env.E2E_USER_PASSWORD;

  if (!password) {
    throw new Error(
      'E2E_USER_PASSWORD is not set. Export it or write it to ' +
      'apps/web/.env.test.local before running the e2e suite. ' +
      'See apps/web/playwright.config.ts for details.',
    );
  }

  // ── ensure .auth dir exists ──
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });

  await page.goto('/login');

  // LoginPage uses react-bootstrap <Form.Control type="email"/password>
  // with placeholder text driven by i18n. Targeting by `type` is the
  // sturdiest selector — survives copy changes + locale switches.
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator('button[type="submit"]').click();

  // After a successful login the LoginPage navigates to /dashboard
  // (replace: true). Wait for the URL to flip AND for the dashboard
  // shell to actually render — JWT can land in localStorage a tick
  // before the app remounts, and persisting too early captures a
  // half-hydrated state.
  await page.waitForURL('**/dashboard', { timeout: 30_000 });
  await expect(page.locator('.dcc-chat-row')).toBeVisible({ timeout: 30_000 });

  // Sanity check: the AuthContext stores the JWT under `user`.
  const userBlob = await page.evaluate(() => localStorage.getItem('user'));
  expect(userBlob, 'localStorage.user should be populated after login').toBeTruthy();

  await page.context().storageState({ path: STORAGE_STATE });
});
