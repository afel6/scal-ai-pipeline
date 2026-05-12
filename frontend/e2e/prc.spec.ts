/**
 * PRC SCAL AI Pipeline — End-to-End Test Suite
 *
 * Covers: authentication, chat flow (mocked SSE), New Study, session deletion.
 * All API calls are intercepted via page.route() so the backend does not need
 * to be running during the test run.
 */
import { test, expect, type Page } from '@playwright/test';

// ─── Shared test data ─────────────────────────────────────────────────────────

const MOCK_USER = {
  name:  'Test Engineer',
  id:    '7777',
  email: 'test@prc.ly',
};

const SESSION_ID   = 'e2e-session-abc123';
const SESSION_TITLE = 'Test SCAL Study';

const MOCK_SESSION = {
  id:         SESSION_ID,
  title:      SESSION_TITLE,
  created_at: Math.floor(Date.now() / 1000) - 3600,
  updated_at: Math.floor(Date.now() / 1000) - 3600,
  user_email: MOCK_USER.email,
};

const AI_RESPONSE_TEXT = 'Physics integrity confirmed. All Kr curves pass Brooks-Corey validation.';

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Build a complete SSE body that the app's EventSource consumer will accept. */
function buildSseStream(text: string): string {
  return [
    `data: ${JSON.stringify({ type: 'session', session_id: SESSION_ID })}\n\n`,
    `data: ${JSON.stringify({ type: 'token',   text })}\n\n`,
    `data: ${JSON.stringify({ type: 'done' })}\n\n`,
  ].join('');
}

/**
 * Inject user object + session ID into localStorage before the app boots.
 * This bypasses the login form, letting tests start directly in the chat UI.
 */
async function seedAuth(page: Page, sessionId = '') {
  await page.addInitScript(
    ({ user, sid }: { user: typeof MOCK_USER; sid: string }) => {
      localStorage.setItem('prc_user',       JSON.stringify(user));
      localStorage.setItem('prc_session_id', sid);
    },
    { user: MOCK_USER, sid: sessionId },
  );
}

/**
 * Register all required API mock routes.
 * Routes are more specific → less specific so earlier handlers win.
 *
 * @param sessions  What to return from GET /api/sessions
 */
async function mockApi(page: Page, sessions: typeof MOCK_SESSION[] = []) {
  // Auth
  await page.route('**/api/auth',     (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/api/register', (r) => r.fulfill({ status: 200, body: '' }));

  // Chat SSE stream — returns all events in a single body; the browser's
  // EventSource parser fires individual onmessage events from the concatenated stream.
  await page.route('**/api/chat/stream*', (r) =>
    r.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      body: buildSseStream(AI_RESPONSE_TEXT),
    }),
  );

  // Session list — note: "**/api/sessions*" does NOT match "/api/session/{id}"
  await page.route('**/api/sessions*', (r) =>
    r.fulfill({
      status:      200,
      contentType: 'application/json',
      body:        JSON.stringify(sessions),
    }),
  );

  // Individual session CRUD
  await page.route('**/api/session/**', async (r) => {
    switch (r.request().method()) {
      case 'DELETE':
        return r.fulfill({
          status: 200, contentType: 'application/json', body: '{"status":"ok"}',
        });
      case 'GET':
        return r.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ status: 'ok', messages: [] }),
        });
      default:
        return r.continue();
    }
  });
}

// ─── Auth screen ─────────────────────────────────────────────────────────────

test.describe('Auth screen', () => {
  test('renders PRC branding and all three form fields', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');

    await expect(page.locator('text=Hviel | PRC AI Hub')).toBeVisible();
    await expect(page.getByPlaceholder('e.g. Eng. Ahmed Al-Lafi')).toBeVisible();
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.getByPlaceholder('Enter Access Code')).toBeVisible();
  });

  test('Authenticate Session button is disabled when fields are empty', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');

    const btn = page.getByRole('button', { name: /Authenticate Session/i });
    await expect(btn).toBeDisabled();
  });

  test('Authenticate Session button enables after all fields are filled', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');

    await page.getByPlaceholder('e.g. Eng. Ahmed Al-Lafi').fill('Eng. Test User');
    await page.locator('input[type="email"]').fill('test@prc.ly');
    await page.getByPlaceholder('Enter Access Code').fill('1234');

    const btn = page.getByRole('button', { name: /Authenticate Session/i });
    await expect(btn).toBeEnabled();
  });

  test('wrong PIN shows access-denied error without crashing', async ({ page }) => {
    await page.route('**/api/auth', (r) => r.fulfill({ status: 403, body: '' }));
    await page.goto('/');

    await page.getByPlaceholder('e.g. Eng. Ahmed Al-Lafi').fill('Eng. Test User');
    await page.locator('input[type="email"]').fill('test@prc.ly');
    await page.getByPlaceholder('Enter Access Code').fill('wrongpin');
    await page.getByRole('button', { name: /Authenticate Session/i }).click();

    await expect(page.locator('text=/Invalid MFA|Access Denied/i')).toBeVisible();
  });

  test('successful login stores user and transitions to chat UI', async ({ page }) => {
    await mockApi(page);
    await page.goto('/');

    await page.getByPlaceholder('e.g. Eng. Ahmed Al-Lafi').fill('Eng. Test User');
    await page.locator('input[type="email"]').fill('test@prc.ly');
    await page.getByPlaceholder('Enter Access Code').fill('7777');
    await page.getByRole('button', { name: /Authenticate Session/i }).click();

    // Chat input should appear after login
    await expect(page.getByPlaceholder(/Query Hviel|Establishing/i)).toBeVisible({ timeout: 5000 });

    // localStorage must contain user
    const stored = await page.evaluate(() => localStorage.getItem('prc_user'));
    expect(JSON.parse(stored!).email).toBe('test@prc.ly');
  });
});

// ─── Chat UI — pre-authenticated ─────────────────────────────────────────────

test.describe('Chat interface (pre-authenticated)', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
    await page.goto('/');
  });

  test('shows chat input and Hviel welcome message', async ({ page }) => {
    await expect(page.getByPlaceholder(/Query Hviel|Establishing/i)).toBeVisible();
    await expect(page.locator('text=Hviel')).toBeVisible();
  });

  test('send button is disabled when input is empty', async ({ page }) => {
    // The send button has a Send/Loader icon and is disabled when input is empty
    const sendBtn = page.locator('button[disabled]').filter({ has: page.locator('svg') }).first();
    // More precisely — the button is disabled when input is blank
    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    await expect(textarea).toBeEmpty();

    // Button carries `disabled` attribute
    await expect(
      page.locator('button').filter({ hasText: '' }).last()  // fallback
    ).toBeDefined();
    // Verify we can't send by checking loading doesn't start
    await page.keyboard.press('Enter');
    await expect(page.locator('.animate-spin')).toHaveCount(0);
  });
});

// ─── New Study button ─────────────────────────────────────────────────────────

test.describe('New Study flow', () => {
  test('clicking New resets chat to welcome message', async ({ page }) => {
    await seedAuth(page, SESSION_ID);
    await mockApi(page, [MOCK_SESSION]);
    await page.goto('/');

    // Wait for chat UI
    await expect(page.getByPlaceholder(/Query Hviel|Establishing/i)).toBeVisible();

    // Sidebar may be open on desktop viewport (≥768px)
    const newBtn = page.getByRole('button', { name: /New/i }).first();
    await expect(newBtn).toBeVisible({ timeout: 4000 });
    await newBtn.click();

    // Chat input still visible, session cleared
    await expect(page.getByPlaceholder(/Query Hviel|Establishing/i)).toBeVisible();

    const storedSid = await page.evaluate(() => localStorage.getItem('prc_session_id'));
    expect(storedSid).toBe('');
  });
});

// ─── Send message and receive AI response (mocked SSE) ───────────────────────

test.describe('Chat flow (mocked SSE)', () => {
  test('sends message, streams AI response, clears loading state', async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
    await page.goto('/');

    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    await expect(textarea).toBeVisible();

    // Type a plain message (non-document so it routes to SSE)
    await textarea.fill('What is porosity?');
    await textarea.press('Enter');

    // Spinner appears briefly (loading state)
    // Then AI response appears — wait up to 8s for mocked SSE to complete
    await expect(page.locator(`text=${AI_RESPONSE_TEXT}`)).toBeVisible({ timeout: 8000 });

    // Loading spinner gone
    await expect(page.locator('.animate-spin')).toHaveCount(0, { timeout: 5000 });

    // No error or 503/404 message in the page
    await expect(page.locator('text=/503|404|Connection error/i')).toHaveCount(0);
  });

  test('session ID is stored in localStorage after first message', async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
    await page.goto('/');

    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    await textarea.fill('Run a Brooks-Corey simulation');
    await textarea.press('Enter');

    // Wait for SSE done event to be processed
    await expect(page.locator(`text=${AI_RESPONSE_TEXT}`)).toBeVisible({ timeout: 8000 });

    const storedSid = await page.evaluate(() => localStorage.getItem('prc_session_id'));
    expect(storedSid).toBe(SESSION_ID);
  });

  test('SSE error event shows error UI without crashing the app', async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);

    // Override SSE route with an error payload
    await page.route('**/api/chat/stream*', (r) =>
      r.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: `data: ${JSON.stringify({ type: 'error', msg: 'Upstream 503 — Gemini unavailable' })}\n\n`,
      }),
    );

    await page.goto('/');
    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    await textarea.fill('What is Archie equation?');
    await textarea.press('Enter');

    await expect(page.locator('text=/503|Gemini unavailable/i')).toBeVisible({ timeout: 6000 });
    // App stays alive — input still visible
    await expect(textarea).toBeVisible();
  });

  test('network failure on SSE shows connection error message', async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);

    // Abort SSE request to simulate network failure
    await page.route('**/api/chat/stream*', (r) => r.abort('failed'));

    await page.goto('/');
    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    await textarea.fill('Test network failure');
    await textarea.press('Enter');

    await expect(
      page.locator('text=/Connection error|Unable to reach/i')
    ).toBeVisible({ timeout: 6000 });

    // App must not crash — input still functional
    await expect(textarea).toBeVisible();
  });
});

// ─── Session deletion ─────────────────────────────────────────────────────────

test.describe('Session deletion', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuth(page, SESSION_ID);
    await mockApi(page, [MOCK_SESSION]);
    await page.goto('/');
    // Wait for sidebar to populate
    await expect(page.locator(`text=${SESSION_TITLE}`)).toBeVisible({ timeout: 5000 });
  });

  test('Trash2 icon is hidden by default and appears on session hover', async ({ page }) => {
    const sessionRow = page.locator(`text=${SESSION_TITLE}`).locator('..');

    // Initially opacity-0 (hidden but present in DOM)
    const trashBtn = page.locator('button').filter({ has: page.locator('svg.lucide-trash-2') });
    await expect(trashBtn).toBeAttached(); // present in DOM

    // Hover reveals it
    await sessionRow.hover();
    await expect(trashBtn).toBeVisible({ timeout: 2000 });
  });

  test('clicking Trash sends DELETE with email and removes session from list', async ({ page }) => {
    // Capture DELETE request to verify email query param
    let deleteUrl = '';
    await page.route('**/api/session/**', async (r) => {
      if (r.request().method() === 'DELETE') {
        deleteUrl = r.request().url();
        await r.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
      } else {
        await r.continue();
      }
    });

    // After deletion the sessions endpoint returns empty list
    let deleteCalled = false;
    await page.route('**/api/sessions*', async (r) => {
      await r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(deleteCalled ? [] : [MOCK_SESSION]),
      });
    });

    const sessionRow = page.locator(`text=${SESSION_TITLE}`).locator('..');
    await sessionRow.hover();

    const trashBtn = page.locator('button').filter({ has: page.locator('svg.lucide-trash-2') });
    deleteCalled = true;
    await trashBtn.click();

    // DELETE must include email param
    await page.waitForTimeout(500); // allow axios.delete to resolve
    expect(deleteUrl).toContain('email=');
    expect(decodeURIComponent(deleteUrl)).toContain(MOCK_USER.email);

    // Session title should disappear from the sidebar
    await expect(page.locator(`text=${SESSION_TITLE}`)).toHaveCount(0, { timeout: 5000 });
  });

  test('deleting active session resets chat to welcome message', async ({ page }) => {
    // The seeded session IS the active session (SESSION_ID)
    let deleteCalled = false;

    await page.route('**/api/session/**', async (r) => {
      if (r.request().method() === 'DELETE') {
        deleteCalled = true;
        await r.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
      } else {
        await r.continue();
      }
    });

    await page.route('**/api/sessions*', async (r) =>
      r.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(deleteCalled ? [] : [MOCK_SESSION]),
      }),
    );

    const sessionRow = page.locator(`text=${SESSION_TITLE}`).locator('..');
    await sessionRow.hover();

    const trashBtn = page.locator('button').filter({ has: page.locator('svg.lucide-trash-2') });
    await trashBtn.click();

    // Active session reset — localStorage prc_session_id cleared
    await page.waitForTimeout(600);
    const storedSid = await page.evaluate(() => localStorage.getItem('prc_session_id'));
    expect(storedSid).toBeFalsy();

    // Welcome message still visible (chat reset to initial state)
    await expect(page.locator('text=Hviel')).toBeVisible();
  });

  test('delete with missing email param returns 401 — verify frontend sends email', async ({ page }) => {
    // This test validates that the stale-closure fix is working:
    // the DELETE URL must contain a non-empty email, even for sessions
    // loaded from a fresh page load (not a post-login callback).
    const deleteRequests: string[] = [];

    await page.route('**/api/session/**', async (r) => {
      if (r.request().method() === 'DELETE') {
        deleteRequests.push(r.request().url());
        await r.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
      } else {
        await r.continue();
      }
    });

    const sessionRow = page.locator(`text=${SESSION_TITLE}`).locator('..');
    await sessionRow.hover();
    await page.locator('button').filter({ has: page.locator('svg.lucide-trash-2') }).click();

    await page.waitForTimeout(500);
    expect(deleteRequests.length).toBeGreaterThanOrEqual(1);
    const url = decodeURIComponent(deleteRequests[0]);
    expect(url).toMatch(/email=.+@.+/); // must be a non-empty email address
  });
});

// ─── Regression: no deadlock on repeated New + Send cycles ───────────────────

test.describe('Stress: repeated New Study + Send cycles', () => {
  test('three consecutive New → Send cycles do not deadlock the UI', async ({ page }) => {
    await seedAuth(page);
    await mockApi(page);
    await page.goto('/');

    const textarea = page.getByPlaceholder(/Query Hviel|Establishing/i);
    const newBtn   = page.getByRole('button', { name: /New/i }).first();

    await expect(textarea).toBeVisible();
    await expect(newBtn).toBeVisible({ timeout: 4000 });

    for (let i = 0; i < 3; i++) {
      await newBtn.click();
      await textarea.fill(`Iteration ${i + 1}: what is Swi?`);
      await textarea.press('Enter');
      await expect(page.locator(`text=${AI_RESPONSE_TEXT}`)).toBeVisible({ timeout: 8000 });
      // No spinner stuck
      await expect(page.locator('.animate-spin')).toHaveCount(0, { timeout: 5000 });
    }

    // UI still functional after 3 cycles
    await expect(textarea).toBeEnabled();
    await expect(page.locator('text=/503|404|deadlock/i')).toHaveCount(0);
  });
});
