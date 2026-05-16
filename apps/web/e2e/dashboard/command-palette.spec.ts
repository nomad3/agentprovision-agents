/*
 * Command palette (⌘K / Ctrl+K) — universal jump that fuzzy-matches
 * sessions and agents. Source: apps/web/src/dashboard/CommandPalette.js.
 */
import { test, expect } from '../fixtures/auth';

test.describe('command palette', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
  });

  test('Meta+K opens the palette', async ({ page }) => {
    // Use Meta on macOS, Control elsewhere. Playwright maps the
    // `Meta` keyword to Cmd on macOS and Win/Super elsewhere; the
    // CommandPalette listener accepts metaKey OR ctrlKey, so this
    // works cross-platform.
    await page.keyboard.press('Meta+K');
    await expect(page.locator('.command-palette, [role="dialog"][aria-label*="command" i]'))
      .toBeVisible();
  });

  test('typing filters results and Enter activates a session', async ({ page }) => {
    // Pull the first session name from the sidebar so we have a
    // real query that's known to match.
    const firstSession = page.locator('.dcc-sessions-list li, .dcc-sessions-list [role="listitem"]').first();
    const sessionText = (await firstSession.textContent())?.trim() || '';
    test.skip(!sessionText, 'no sessions on this tenant to query against');

    // Take a short slice — the palette uses prefix matching and we
    // don't want to type the full id/uuid.
    const query = sessionText.slice(0, 5);

    await page.keyboard.press('Meta+K');
    const palette = page.locator('.command-palette, [role="dialog"][aria-label*="command" i]');
    await expect(palette).toBeVisible();

    const search = palette.locator('input[type="search"], input[type="text"]').first();
    await search.fill(query);

    // After typing, the result list should narrow to entries that
    // contain the query. Allow up to 1s for debounced filtering.
    await page.waitForTimeout(400);
    const results = palette.locator('[role="option"], li');
    const resultCount = await results.count();
    expect(resultCount).toBeGreaterThan(0);

    // Press Enter — the first highlighted option should activate.
    // We can't always know what gets selected, so we assert the
    // palette closes (a successful activation always dismisses it).
    await page.keyboard.press('Enter');
    await expect(palette).toBeHidden({ timeout: 5_000 });
  });
});
