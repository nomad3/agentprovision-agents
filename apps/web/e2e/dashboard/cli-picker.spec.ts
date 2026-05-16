/*
 * Inline CLI picker (chat-header tenant-default-CLI switch).
 *
 * Surface lives at apps/web/src/dashboard/InlineCliPicker.js — calls
 * brandingService.getFeatures() on mount and brandingService.updateFeatures()
 * on change. The underlying knob is `tenant_features.default_cli_platform`.
 */
import { test, expect } from '../fixtures/auth';

test.describe('inline CLI picker', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
  });

  test('renders in chat header with "Tenant CLI" label', async ({ page }) => {
    const picker = page.locator('.inline-cli-picker').first();
    await expect(picker).toBeVisible();
    await expect(picker.locator('.inline-cli-picker-label')).toHaveText('Tenant CLI');
  });

  test('default value matches branding API state', async ({ page }) => {
    // Hit the same endpoint the component uses, then assert the
    // <select> value mirrors it. Means the picker is faithfully
    // reading state instead of defaulting to Auto regardless.
    const apiValue = await page.evaluate(async () => {
      const user = JSON.parse(localStorage.getItem('user') || 'null');
      const res = await fetch('/api/v1/branding/features', {
        headers: { Authorization: `Bearer ${user?.access_token || ''}` },
      });
      if (!res.ok) return null;
      const json = await res.json();
      return json?.default_cli_platform ?? null;
    });

    const select = page.locator('.inline-cli-picker-select').first();
    await expect(select).toBeVisible();
    const expected = apiValue || '__auto__';
    await expect(select).toHaveValue(expected);
  });

  test('changing value to Codex saves + persists across reload', async ({ page }) => {
    // Capture the PUT request so we can verify the body shape rather
    // than relying solely on the UI ✓ check.
    const requestPromise = page.waitForRequest(
      (req) =>
        req.url().includes('/api/v1/branding/features') &&
        (req.method() === 'PUT' || req.method() === 'PATCH' || req.method() === 'POST'),
    );

    const select = page.locator('.inline-cli-picker-select').first();
    await select.selectOption('codex');

    const req = await requestPromise;
    const body = req.postDataJSON();
    expect(body).toMatchObject({ default_cli_platform: 'codex' });

    // The component renders a ✓ for ~2s after a successful save.
    await expect(page.locator('.inline-cli-picker-saved').first()).toBeVisible();

    // Reload — value should still be codex.
    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
    await expect(page.locator('.inline-cli-picker-select').first()).toHaveValue('codex');

    // ── cleanup ──
    // Restore Auto so subsequent runs (and other agents poking the
    // same tenant) don't inherit our test value. Use the same API
    // path the picker would; no need to drive the UI again.
    await page.evaluate(async () => {
      const user = JSON.parse(localStorage.getItem('user') || 'null');
      await fetch('/api/v1/branding/features', {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${user?.access_token || ''}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ default_cli_platform: null }),
      });
    });
  });

  test('"Open in full chat" link is NOT in the DOM', async ({ page }) => {
    // The inline picker replaced a deprecated link that used to send
    // users out to the standalone /chat page. Guard against
    // regressions that bring the link back.
    await expect(page.getByRole('link', { name: /open in full chat/i })).toHaveCount(0);
  });
});
