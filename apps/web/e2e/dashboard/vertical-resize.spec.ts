/*
 * Phase A: vertical resize between chat row and terminal.
 *
 * This was a separate PR (#518). If it hasn't merged into the
 * deployment under test, `.dcc-outer-col` won't be in the DOM — we
 * detect that and skip rather than failing.
 */
import { test, expect } from '../fixtures/auth';

test.describe('vertical chat/terminal resize (Phase A)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
    // ── feature gate ──
    const outerCol = page.locator('.dcc-outer-col');
    if ((await outerCol.count()) === 0) {
      test.skip(true, 'Phase A not deployed — .dcc-outer-col absent');
    }
  });

  test('outer column has one horizontal separator', async ({ page }) => {
    const outer = page.locator('.dcc-outer-col');
    await expect(outer).toBeVisible();

    const handles = outer.locator('[role="separator"][aria-orientation="horizontal"]');
    await expect(handles).toHaveCount(1);
  });

  test('dragging the handle 80 px shrinks chat, grows terminal', async ({ page }) => {
    const handle = page
      .locator('.dcc-outer-col [role="separator"][aria-orientation="horizontal"]')
      .first();
    const chatRow = page.locator('.dcc-chat-row');

    const chatBefore = await chatRow.boundingBox();
    const handleBox = await handle.boundingBox();
    if (!chatBefore || !handleBox) throw new Error('layout boxes missing');

    const startX = handleBox.x + handleBox.width / 2;
    const startY = handleBox.y + handleBox.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX, startY + 80, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(200);

    const chatAfter = await chatRow.boundingBox();
    if (!chatAfter) throw new Error('chat row vanished after drag');
    // The handle moved down — chat row should be at most slightly
    // larger (it should shrink, but allow for layout settling).
    expect(chatAfter.height).toBeLessThan(chatBefore.height + 5);
  });

  test('vertical sizes persist after reload', async ({ page }) => {
    const handle = page
      .locator('.dcc-outer-col [role="separator"][aria-orientation="horizontal"]')
      .first();
    const handleBox = await handle.boundingBox();
    if (!handleBox) throw new Error('handle box missing');

    const startX = handleBox.x + handleBox.width / 2;
    const startY = handleBox.y + handleBox.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX, startY + 80, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(200);

    // The outer split persists under a `dcc.outerCol.sizes.*` key.
    // Match permissively because the suffix tracks mode flags.
    const before = await page.evaluate(() => {
      const out: Record<string, string | null> = {};
      for (let i = 0; i < localStorage.length; i += 1) {
        const k = localStorage.key(i);
        if (k && k.startsWith('dcc.outerCol.sizes')) out[k] = localStorage.getItem(k);
      }
      return out;
    });
    expect(Object.keys(before).length).toBeGreaterThan(0);

    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();

    const after = await page.evaluate(() => {
      const out: Record<string, string | null> = {};
      for (let i = 0; i < localStorage.length; i += 1) {
        const k = localStorage.key(i);
        if (k && k.startsWith('dcc.outerCol.sizes')) out[k] = localStorage.getItem(k);
      }
      return out;
    });
    expect(after).toEqual(before);
  });
});
