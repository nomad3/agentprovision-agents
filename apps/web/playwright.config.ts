/*
 * Playwright config for the Alpha Control Center dashboard E2E suite.
 *
 * Targets the live production deployment at https://agentprovision.com
 * so tests exercise the real backend, real branding API, real session
 * lifecycle. There is no staging tenant we trust for these flows, and
 * the suite is deliberately read-mostly + idempotent (it toggles a
 * tenant feature flag and clicks UI affordances, no destructive writes
 * beyond that).
 *
 * Chromium-only on purpose: the production user base ships through
 * Chrome (Luna native client embeds WebKit but the dashboard is a
 * normal web page). Spending CI minutes on Firefox/WebKit gives us
 * little signal for the surfaces we actually care about.
 *
 * Auth flow:
 *   - The `setup` project runs `e2e/fixtures/auth.setup.ts` once and
 *     persists a logged-in storageState to `e2e/.auth/saguilera.json`.
 *   - Every other project depends on `setup` and reuses that file via
 *     the `storageState` option, so the dashboard suite never logs in
 *     a second time within a run.
 *   - Credentials come from `.env.test.local` (gitignored) or the env
 *     directly: `E2E_USER_EMAIL` / `E2E_USER_PASSWORD`.
 */
import { defineConfig, devices } from '@playwright/test';
import path from 'path';

// Best-effort load of `.env.test.local` so devs don't have to remember
// to `export` env vars before each run. We intentionally do NOT pull
// in `dotenv` as a dep — keep the install footprint tight — and
// instead parse the file inline. If it's missing we just fall through
// to whatever the shell environment provides.
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires, global-require
  const fs = require('fs');
  const envPath = path.resolve(__dirname, '.env.test.local');
  if (fs.existsSync(envPath)) {
    const text = fs.readFileSync(envPath, 'utf8');
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eq = trimmed.indexOf('=');
      if (eq === -1) continue;
      const k = trimmed.slice(0, eq).trim();
      let v = trimmed.slice(eq + 1).trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      if (!(k in process.env)) process.env[k] = v;
    }
  }
} catch {
  /* env hydration is best-effort; tests will fail loudly with a clear
   * message if the email/password are missing anyway. */
}

const STORAGE_STATE = path.resolve(__dirname, 'e2e/.auth/saguilera.json');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // ── retry policy ──
  // 1 retry on CI to absorb transient prod hiccups (cold lambdas,
  // SSE reconnects); 0 locally so devs see the real failure first.
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'https://agentprovision.com',
    // ── trace policy ──
    // Trace on first retry only — keeps green runs cheap, but if a
    // flake retries we have full timeline + DOM snapshots to debug.
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      // One-time interactive(-ish) login that writes storageState.
      // Splitting this out lets the dashboard projects skip the login
      // form entirely and start each spec already authenticated.
      name: 'setup',
      testMatch: /fixtures\/auth\.setup\.ts/,
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: STORAGE_STATE,
      },
      dependencies: ['setup'],
      testIgnore: /fixtures\/auth\.setup\.ts/,
    },
  ],
});
