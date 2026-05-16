/*
 * Dashboard layout: panes, mode toggle, separator resize, double-click reset.
 *
 * Phase A (vertical chat/terminal split) is covered separately in
 * vertical-resize.spec.ts. Here we exercise the horizontal row that
 * holds sessions / chat / activity.
 */
import { test, expect } from '../fixtures/auth';

test.describe('dashboard layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
  });

  test('renders chat row + 3 panes + 2 separators in Pro mode', async ({ page }) => {
    // Pro is the default mode for fresh sessions; the toggle pill
    // surfaces it via .dcc-mode-pill.active on "Pro".
    const proPill = page.locator('.dcc-mode-pill', { hasText: 'Pro' });
    await expect(proPill).toHaveClass(/active/);

    const panes = page.locator('.dcc-chat-row .rs-pane');
    await expect(panes).toHaveCount(3);

    const separators = page.locator('.dcc-chat-row [role="separator"]');
    await expect(separators).toHaveCount(2);
  });

  test('mode toggle: Simple collapses to 2 panes, Pro restores 3', async ({ page }) => {
    // ── Simple ──
    await page.locator('.dcc-mode-pill', { hasText: 'Simple' }).click();
    await expect(page.locator('.dcc-mode-pill', { hasText: 'Simple' })).toHaveClass(/active/);
    // In Simple mode the activity column is hidden; the row falls
    // back to the sessions+chat split (2 panes, 1 separator).
    await expect(page.locator('.dcc-chat-row .rs-pane')).toHaveCount(2);
    await expect(page.locator('.dcc-chat-row [role="separator"]')).toHaveCount(1);

    // ── Pro back ──
    await page.locator('.dcc-mode-pill', { hasText: 'Pro' }).click();
    await expect(page.locator('.dcc-chat-row .rs-pane')).toHaveCount(3);
    await expect(page.locator('.dcc-chat-row [role="separator"]')).toHaveCount(2);
  });

  test('separator drag persists across reload', async ({ page }) => {
    // Clear any pre-existing persisted sizes so the assertion below
    // ("non-default after drag") doesn't false-positive on stale state.
    await page.evaluate(() => localStorage.removeItem('dcc.chatRow.sizes.pro-r'));
    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();

    const firstHandle = page.locator('.dcc-chat-row [role="separator"]').first();
    const box = await firstHandle.boundingBox();
    if (!box) throw new Error('separator handle has no bounding box');

    const startX = box.x + box.width / 2;
    const startY = box.y + box.height / 2;
    // Drag 50 px right. The ResizableSplit listens on pointer events;
    // a single mousedown → move → up reliably triggers the resize.
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 50, startY, { steps: 10 });
    await page.mouse.up();

    // Wait a tick — sizes are committed to localStorage in the
    // pointer-up handler, then again on the next animation frame.
    await page.waitForTimeout(200);

    const persisted = await page.evaluate(() =>
      localStorage.getItem('dcc.chatRow.sizes.pro-r'),
    );
    expect(persisted, 'sizes must be persisted to localStorage after drag').toBeTruthy();

    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
    const afterReload = await page.evaluate(() =>
      localStorage.getItem('dcc.chatRow.sizes.pro-r'),
    );
    expect(afterReload).toBe(persisted);
  });

  test('double-click on separator resets sizes to defaults', async ({ page }) => {
    // Seed a non-default size so the reset has something to undo.
    await page.evaluate(() =>
      localStorage.setItem('dcc.chatRow.sizes.pro-r', JSON.stringify([10, 70, 20])),
    );
    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();

    const seeded = await page.evaluate(() =>
      localStorage.getItem('dcc.chatRow.sizes.pro-r'),
    );
    expect(seeded).toBe(JSON.stringify([10, 70, 20]));

    const firstHandle = page.locator('.dcc-chat-row [role="separator"]').first();
    await firstHandle.dblclick();

    // After reset the key is either removed OR rewritten to defaults.
    // Both are correct, so we just assert it no longer matches the
    // exotic value we seeded.
    await page.waitForTimeout(200);
    const after = await page.evaluate(() =>
      localStorage.getItem('dcc.chatRow.sizes.pro-r'),
    );
    expect(after).not.toBe(JSON.stringify([10, 70, 20]));
  });
});
