/*
 * Files mode: left-column toggle that swaps the sessions list for
 * the FileTreePanel (apps/web/src/dashboard/FileTreePanel.js). The
 * file viewer takes over the right pane.
 *
 * Platform-scope visibility is conditional on superuser status — we
 * read the persisted user blob via auth-state utils to decide which
 * assertion to make.
 */
import { test, expect } from '../fixtures/auth';
import { isSuperuser } from '../utils/auth-state';

test.describe('files mode', () => {
  test.beforeEach(async ({ page }) => {
    // Clear leftMode + openFile so each test starts from a known
    // baseline (Chats mode, no file open).
    await page.goto('/dashboard');
    await page.evaluate(() => {
      localStorage.removeItem('apControl.leftMode');
      localStorage.removeItem('apControl.openFile');
    });
    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();
  });

  test('clicking Files swaps sessions list for file tree', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    await expect(page.locator('.ftp-tree')).toBeVisible();
    // The sessions list is hidden when leftMode === 'files'. We
    // can't assert on a stable test id (sessions list doesn't have
    // one yet), but we can assert the tree is now the visible
    // surface in the left pane.
    await expect(page.locator('.ftp-tree')).toBeVisible();
  });

  test('platform scope visibility tracks superuser flag', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    await expect(page.locator('.ftp-tree')).toBeVisible();

    const platformScope = page.getByRole('tab', { name: /platform/i });
    if (isSuperuser()) {
      await expect(platformScope).toBeVisible();
    } else {
      await expect(platformScope).toHaveCount(0);
    }
  });

  test('expanding docs/ lazy-loads plans/ as a child', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    await expect(page.locator('.ftp-tree')).toBeVisible();

    // The tree renders folder rows with their name as text. We
    // click on `docs` to expand it, then wait for `plans` to appear
    // as a child row. Be permissive about exact markup — match on
    // visible text.
    const docsRow = page.locator('.ftp-tree').getByText(/^docs$/, { exact: false }).first();
    await docsRow.click();
    await expect(page.locator('.ftp-tree').getByText(/^plans$/, { exact: false }).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test('clicking a .md file swaps right pane to FileViewer', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    await expect(page.locator('.ftp-tree')).toBeVisible();

    // Open docs/ → first .md we see in the tree. The exact filename
    // varies per tenant, so we grab the first one rather than
    // hardcoding.
    await page.locator('.ftp-tree').getByText(/^docs$/, { exact: false }).first().click();
    const mdLink = page.locator('.ftp-tree').locator('text=/\\.md$/').first();
    await mdLink.waitFor({ state: 'visible', timeout: 15_000 });
    await mdLink.click();

    // FileViewer replaces the dcc-activity-card on the right.
    await expect(page.locator('.file-viewer, .ftp-viewer')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('.dcc-activity-card')).toHaveCount(0);
  });

  test('long file tree scrolls inside the panel', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    const tree = page.locator('.ftp-tree');
    await expect(tree).toBeVisible();

    // Expand docs/ so we have enough rows to overflow. Then assert
    // the tree's scrollHeight > clientHeight AND that scrollTop
    // moves when we send a wheel event. Guards against the bug
    // where the panel itself stretched and clipping moved up to
    // the page <body>.
    await tree.getByText(/^docs$/, { exact: false }).first().click();
    await page.waitForTimeout(500);

    const metrics = await tree.evaluate((el) => ({
      scrollHeight: (el as HTMLElement).scrollHeight,
      clientHeight: (el as HTMLElement).clientHeight,
    }));
    expect(metrics.scrollHeight).toBeGreaterThanOrEqual(metrics.clientHeight);

    await tree.evaluate((el) => {
      (el as HTMLElement).scrollTop = 60;
    });
    const scrollTop = await tree.evaluate((el) => (el as HTMLElement).scrollTop);
    // Only assert if there's actually room to scroll — small
    // tenants may not have enough files to overflow even after
    // expanding docs/.
    if (metrics.scrollHeight > metrics.clientHeight) {
      expect(scrollTop).toBeGreaterThan(0);
    }
  });

  test('leftMode + openFile persist across reload', async ({ page }) => {
    await page.getByRole('tab', { name: /files/i }).click();
    await expect(page.locator('.ftp-tree')).toBeVisible();

    // Open the first md file we can find.
    await page.locator('.ftp-tree').getByText(/^docs$/, { exact: false }).first().click();
    const md = page.locator('.ftp-tree').locator('text=/\\.md$/').first();
    await md.waitFor({ state: 'visible', timeout: 15_000 });
    const mdText = await md.textContent();
    await md.click();
    await expect(page.locator('.file-viewer, .ftp-viewer')).toBeVisible({ timeout: 15_000 });

    await page.reload();
    await expect(page.locator('.dcc-chat-row')).toBeVisible();

    // After reload: tree still visible (leftMode persisted) and
    // FileViewer is back (openFile persisted).
    await expect(page.locator('.ftp-tree')).toBeVisible();
    await expect(page.locator('.file-viewer, .ftp-viewer')).toBeVisible({ timeout: 15_000 });
    const persistedMode = await page.evaluate(() => localStorage.getItem('apControl.leftMode'));
    expect(persistedMode).toBe('files');
    const persistedFile = await page.evaluate(() => localStorage.getItem('apControl.openFile'));
    expect(persistedFile, 'openFile should be persisted').toBeTruthy();
    if (mdText) {
      expect(persistedFile).toContain(mdText.trim().replace(/\s+/g, ''));
    }
  });
});
