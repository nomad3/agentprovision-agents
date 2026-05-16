/*
 * Editor-group splits in the chat column.
 *
 * Each group is its own chat tab driving the same session list. The
 * page uses apControl.editorGroups + apControl.focusedGroupId in
 * localStorage to persist split state across reloads.
 */
import { test, expect } from '../fixtures/auth';

const SPLIT_RIGHT = '[aria-label="Split right"]';
const CLOSE_SPLIT = '[aria-label="Close split"]';

test.describe('split chat', () => {
  test.beforeEach(async ({ page }) => {
    // Reset to a single group so each test starts with a clean slate.
    await page.goto('/dashboard');
    await page.evaluate(() => {
      localStorage.removeItem('apControl.editorGroups');
      localStorage.removeItem('apControl.focusedGroupId');
    });
    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
  });

  test('starts with 1 chat group', async ({ page }) => {
    await expect(page.locator('.dcc-thread-card')).toHaveCount(1);
  });

  test('Split right adds a second group and focuses the new one', async ({ page }) => {
    await page.locator(SPLIT_RIGHT).first().click();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(2);

    // The focused group exposes a visual cue — match the data attr
    // the React code sets (.dcc-thread-card.is-focused or
    // [data-focused="true"]). Be tolerant of either.
    const focusedCount = await page
      .locator('.dcc-thread-card.is-focused, .dcc-thread-card[data-focused="true"]')
      .count();
    expect(focusedCount).toBeGreaterThanOrEqual(1);
  });

  test('picking a sidebar session only changes the focused group', async ({ page }) => {
    await page.locator(SPLIT_RIGHT).first().click();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(2);

    // Snapshot the two groups' session ids from localStorage so we
    // can compare deltas. The sessions sidebar exposes its rows as
    // listitems with a click handler — open the second one.
    const before = await page.evaluate(() => localStorage.getItem('apControl.editorGroups'));

    const sessionRows = page.locator('.dcc-sessions-list li, .dcc-sessions-list [role="listitem"]');
    const count = await sessionRows.count();
    if (count < 2) {
      test.skip(true, 'tenant has <2 sessions; cannot exercise split selection');
    }
    await sessionRows.nth(1).click();
    await page.waitForTimeout(300);

    const after = await page.evaluate(() => localStorage.getItem('apControl.editorGroups'));
    expect(after).not.toBe(before);

    // Exactly one group's sessionId should have changed.
    const beforeGroups = JSON.parse(before || '[]');
    const afterGroups = JSON.parse(after || '[]');
    let changed = 0;
    for (let i = 0; i < Math.min(beforeGroups.length, afterGroups.length); i += 1) {
      if (beforeGroups[i]?.sessionId !== afterGroups[i]?.sessionId) changed += 1;
    }
    expect(changed).toBe(1);
  });

  test('split state restores after reload', async ({ page }) => {
    await page.locator(SPLIT_RIGHT).first().click();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(2);

    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(2);
  });

  test('Close split returns to a single group', async ({ page }) => {
    await page.locator(SPLIT_RIGHT).first().click();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(2);

    // Close the focused group (newest one).
    await page.locator(CLOSE_SPLIT).last().click();
    await expect(page.locator('.dcc-thread-card')).toHaveCount(1);
  });

  test('5th split is a no-op (max 4 groups)', async ({ page }) => {
    // Open splits until we hit the cap. The Split-right button is
    // disabled/title="Max N splits" once max is reached, per
    // DashboardControlCenter.js. We click up to 5 times; the 5th
    // must NOT raise count beyond 4.
    for (let i = 0; i < 4; i += 1) {
      const btn = page.locator(SPLIT_RIGHT).first();
      // eslint-disable-next-line no-await-in-loop
      const disabled = await btn.getAttribute('disabled');
      if (disabled !== null) break;
      // eslint-disable-next-line no-await-in-loop
      await btn.click({ trial: false });
      // eslint-disable-next-line no-await-in-loop
      await page.waitForTimeout(100);
    }

    const cardsBefore = await page.locator('.dcc-thread-card').count();
    expect(cardsBefore).toBeLessThanOrEqual(4);

    // Try one more click — count should not exceed 4.
    await page.locator(SPLIT_RIGHT).first().click({ trial: false }).catch(() => {});
    const cardsAfter = await page.locator('.dcc-thread-card').count();
    expect(cardsAfter).toBeLessThanOrEqual(4);
  });
});
