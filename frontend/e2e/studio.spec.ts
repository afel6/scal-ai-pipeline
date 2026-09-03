/**
 * E2E verification for the additive "Petrophysical Studio" tab.
 * Confirms the 3-pane Glass-Brutalist layout renders, the Corey sliders redraw
 * the SVG live, and switching back to Chats leaves the existing flow intact.
 * All network is mocked — no backend required.
 */
import { test, expect, type Page } from '@playwright/test';

test.use({ viewport: { width: 1440, height: 900 } });

const MOCK_USER = { name: 'Test Engineer', id: '7777', email: 'test@prc.ly' };

async function seedAuth(page: Page) {
  await page.addInitScript((user) => {
    localStorage.setItem('prc_user', JSON.stringify(user));
    localStorage.setItem('prc_session_id', '');
  }, MOCK_USER);
}

async function mockApi(page: Page) {
  await page.route('**/health',                (r) => r.fulfill({ status: 200, body: 'ok' }));
  await page.route('**/api/clear-user-files',  (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/api/sessions*',         (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/session/**',        (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok","messages":[]}' }));
  await page.route('**/api/chat/stream*',      (r) => r.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body: `data: ${JSON.stringify({ type: 'token', text: 'Studio online.' })}\n\ndata: ${JSON.stringify({ type: 'done' })}\n\n`,
  }));
}

test.describe('Petrophysical Studio tab', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Studio/i }).first().click();
  });

  test('renders ingestion zone, telemetry cards, SVG plotter and param sliders', async ({ page }) => {
    await expect(page.getByTestId('ingestion-zone')).toBeVisible();
    for (const k of ['porosity', 'permeability', 'swi', 'sor']) {
      await expect(page.getByTestId(`tele-${k}`)).toBeVisible();
    }
    await expect(page.getByTestId('corey-svg')).toBeVisible();
    await expect(page.getByTestId('slider-nw')).toBeVisible();
    await expect(page.getByTestId('slider-no')).toBeVisible();

    // Capture proof of the new layout for review.
    await page.screenshot({ path: 'studio-verification.png', fullPage: false });
  });

  test('moving the nw slider redraws the curve (SVG path changes live)', async ({ page }) => {
    const svg = page.getByTestId('corey-svg');
    const before = await svg.innerHTML();
    const slider = page.getByTestId('slider-nw').locator('input[type="range"]');
    await slider.focus();
    await slider.press('ArrowRight');
    await slider.press('ArrowRight');
    await slider.press('ArrowRight');
    const after = await svg.innerHTML();
    expect(after).not.toBe(before); // path "d" recomputed from new exponent
  });

  test('switching back to Chats keeps the existing chat flow intact', async ({ page }) => {
    await page.getByRole('button', { name: /Chats/i }).first().click();
    await expect(page.getByPlaceholder(/Query Hviel|Establishing/i)).toBeVisible();
  });
});
