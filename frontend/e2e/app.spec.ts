import { test, expect } from '@playwright/test';

test('has title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/PRC AI Hub | Hviel/);
});

test('can view auth screen', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=Hviel | PRC AI Hub')).toBeVisible();
  
  const authButton = page.locator('button:has-text("Authenticate Session")');
  await expect(authButton).toBeVisible();
});
