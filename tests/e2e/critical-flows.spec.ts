import { expect, test } from '@playwright/test';

const BASE_URL = 'https://agentprovision.com';
const TEST_EMAIL = 'test@example.com';
const TEST_PASSWORD = 'password';

test.describe('AgentProvision Critical Flows', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the app
    await page.goto(BASE_URL);

    // Login if needed
    const loginButton = page.locator('button:has-text("Login")');
    if (await loginButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await page.fill('input[type="email"]', TEST_EMAIL);
      await page.fill('input[type="password"]', TEST_PASSWORD);
      await loginButton.click();
      await page.waitForURL('**/dashboard', { timeout: 10000 });
    }
  });

  test('should display Claude 4.5 models in agent creation', async ({ page }) => {
    // Navigate to agents page
    await page.goto(`${BASE_URL}/agents`);
    await page.waitForLoadState('networkidle');

    // Click Create Agent button
    await page.click('button:has-text("Create Agent")');

    // Wait for modal to appear
    await page.waitForSelector('text=Create New Agent', { timeout: 5000 });

    // Check if Claude 4.5 models are in the dropdown
    const modelSelect = page.locator('select').filter({ hasText: /Model|model/ }).first();
    await modelSelect.click();

    const opusOption = page.locator('option:has-text("Claude 4.5 Opus")');
    const sonnetOption = page.locator('option:has-text("Claude 4.5 Sonnet")');

    await expect(opusOption).toBeVisible();
    await expect(sonnetOption).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/claude-4-5-models.png' });
  });

  test('should create agent with Claude 4.5 Sonnet', async ({ page }) => {
    await page.goto(`${BASE_URL}/agents`);
    await page.waitForLoadState('networkidle');

    // Click Create Agent
    await page.click('button:has-text("Create Agent")');
    await page.waitForSelector('text=Create New Agent');

    // Fill in the form
    await page.fill('input[name="name"]', 'E2E Test Agent');
    await page.selectOption('select', { label: 'Claude 4.5 Sonnet' });
    await page.fill('textarea[name="description"]', 'Automated E2E test');

    // Submit
    await page.click('button:has-text("Create Agent")');

    // Wait for success
    await page.waitForTimeout(2000);

    // Verify agent appears in list
    await expect(page.locator('text=E2E Test Agent')).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/agent-created.png' });
  });

  test('should navigate to datasets page', async ({ page }) => {
    await page.goto(`${BASE_URL}/datasets`);
    await page.waitForLoadState('networkidle');

    // Check page loaded
    await expect(page.locator('h1, h2').filter({ hasText: /Dataset/i }).first()).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/datasets-page.png' });
  });

  test('should navigate to chat page', async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState('networkidle');

    // Check page loaded
    await expect(page.locator('text=New session').or(page.locator('text=Chat'))).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/chat-page.png' });
  });

  test('should display LLM settings page with providers', async ({ page }) => {
    await page.goto(`${BASE_URL}/llm-settings`);
    await page.waitForLoadState('networkidle');

    // Check providers are displayed
    await expect(page.locator('text=OpenAI').or(page.locator('text=Anthropic'))).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/llm-settings.png' });
  });

  test('should display dashboard analytics', async ({ page }) => {
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForLoadState('networkidle');

    // Check dashboard elements
    await expect(page.locator('text=Dashboard').or(page.locator('text=Analytics'))).toBeVisible();

    // Take screenshot
    await page.screenshot({ path: 'test-results/dashboard.png' });
  });
});
