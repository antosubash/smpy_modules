import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Content snapshots — Import / Export.
 *
 * What earns a browser test here is the part the Python suite cannot reach: the
 * approval gate as an operator experiences it. Whether a restore is reversible,
 * whether the plan tells the truth about what is at stake, and whether a bad
 * bundle explains itself are all decided by what reaches the screen.
 *
 * Each test seeds and tears down its own pages so the file can run against a
 * database other specs share.
 */

const CONTENT = '/pagebuilder/content';
const REVIEW = '/pagebuilder/content/review';

/** Clear the site-wide gate — at most one import is pending at a time, so a
 *  leftover from a previous run would block every test in this file. */
async function clearPendingImport(page: import('@playwright/test').Page) {
  const headers = await csrfHeader(page);
  const pending = await (await page.request.get('/api/pagebuilder/imports/pending')).json();
  if (pending) {
    await page.request.post(`/api/pagebuilder/imports/${pending.id}/reject`, {
      headers,
      data: { note: 'clearing before e2e' },
    });
  }
  return headers;
}

async function createPage(
  page: import('@playwright/test').Page,
  headers: Record<string, string>,
  slug: string,
  title: string,
) {
  const response = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title,
      slug,
      draft_data: { content: [{ type: 'Heading', props: { id: 'h1', text: title } }] },
    },
  });
  expect(response.status()).toBe(201);
  return (await response.json()) as { id: number };
}

test.describe('Content snapshots', () => {
  test('a restore is staged for approval, and applying it is reversible', async ({ page }) => {
    await login(page);
    const headers = await clearPendingImport(page);
    const slug = uniqueSlug('snap');
    const created = await createPage(page, headers, slug, 'Before the snapshot');

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Take snapshot' }).click();
    // The row states what it holds, which is how an operator knows it is real.
    await expect(page.getByText(/\d+ pages? · \d+ redirects?/).first()).toBeVisible();

    // Change the site so the plan has something at stake to report.
    await page.request.put(`/api/pagebuilder/pages/${created.id}`, {
      headers,
      data: { title: 'Edited after the snapshot' },
    });

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Restore…' }).first().click();
    await expect(page).toHaveURL(new RegExp(`${REVIEW}$`));

    // Staging must not have touched the site yet.
    const stillEdited = await page.request.get(`/api/pagebuilder/pages/${created.id}`, {
      headers: { Accept: 'application/json' },
    });
    expect((await stillEdited.json()).title).toBe('Edited after the snapshot');

    // The plan leads with what it will overwrite.
    await expect(page.getByText(/will be overwritten/i)).toBeVisible();

    await page.getByRole('button', { name: /approve & apply/i }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    // The promise the dialog makes is the one the feature has to keep.
    await expect(dialog).toContainText(/taken first/i);
    await dialog.getByRole('button', { name: /^apply$/i }).click();

    await expect(page).toHaveURL(new RegExp(`${CONTENT}$`));
    // The automatic before-snapshot is what makes the apply reversible.
    await expect(page.getByText(/Automatic snapshot taken before restoring/).first()).toBeVisible();

    const reverted = await page.request.get(`/api/pagebuilder/pages/${created.id}`, {
      headers: { Accept: 'application/json' },
    });
    expect((await reverted.json()).title).toBe('Before the snapshot');

    await page.request.delete(`/api/pagebuilder/pages/${created.id}`, { headers });
  });

  test('restoring leaves a page the snapshot never had', async ({ page }) => {
    await login(page);
    const headers = await clearPendingImport(page);

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Take snapshot' }).click();
    await expect(page.getByRole('button', { name: 'Restore…' }).first()).toBeEnabled();

    // Created AFTER the snapshot, so it is absent from the bundle — the exact
    // case "restore never deletes" is about.
    const slug = uniqueSlug('absent');
    const orphan = await createPage(page, headers, slug, 'Absent from the bundle');

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Restore…' }).first().click();
    await expect(page).toHaveURL(new RegExp(`${REVIEW}$`));
    // The approver is told it survives, rather than being left to assume.
    await expect(page.getByText(/will not be deleted/i)).toBeVisible();

    await page.getByRole('button', { name: /approve & apply/i }).click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: /^apply$/i })
      .click();
    await expect(page).toHaveURL(new RegExp(`${CONTENT}$`));

    const survived = await page.request.get(`/api/pagebuilder/pages/${orphan.id}`, {
      headers: { Accept: 'application/json' },
    });
    expect(survived.status()).toBe(200);

    await page.request.delete(`/api/pagebuilder/pages/${orphan.id}`, { headers });
  });

  test('only one restore can be staged at a time', async ({ page }) => {
    await login(page);
    const headers = await clearPendingImport(page);

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Take snapshot' }).click();
    await expect(page.getByRole('button', { name: 'Restore…' }).first()).toBeEnabled();
    await page.getByRole('button', { name: 'Restore…' }).first().click();
    await expect(page).toHaveURL(new RegExp(`${REVIEW}$`));

    await page.goto(CONTENT);
    // The banner is the only thing telling an operator why the buttons died.
    await expect(page.getByText(/waiting for approval/i)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Restore…' }).first()).toBeDisabled();

    // And the rule is enforced behind the UI too, not just in front of it.
    const snapshots = await (await page.request.get('/api/pagebuilder/snapshots')).json();
    const second = await page.request.post(
      `/api/pagebuilder/snapshots/${snapshots.items[0].id}/restore`,
      { headers },
    );
    expect(second.status()).toBe(409);

    await clearPendingImport(page);
  });

  test('a malformed bundle is refused with a reason, not a status code', async ({ page }) => {
    await login(page);
    await clearPendingImport(page);
    await page.goto(CONTENT);

    await page.getByRole('button', { name: /upload bundle/i }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'not-a-bundle.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('this is not a zip archive at all'),
    });
    await dialog.getByRole('button', { name: /^upload$/i }).click();

    // The server's own sentence, not "Request failed (422)".
    await expect(dialog.getByText(/readable zip archive/i)).toBeVisible();
    // And the dialog survives so the operator can pick a different file.
    await expect(dialog.getByRole('button', { name: /cancel/i })).toBeEnabled();
  });

  test('the review screen is reachable with nothing staged', async ({ page }) => {
    await login(page);
    await clearPendingImport(page);

    await page.goto(REVIEW);
    await expect(page.getByText(/no import is staged/i)).toBeVisible();
    await page.getByRole('link', { name: /back to snapshots/i }).click();
    await expect(page).toHaveURL(new RegExp(`${CONTENT}$`));
  });

  test('no console errors on the snapshot screen', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    page.on('pageerror', (e) => errors.push(e.message));

    await login(page);
    await page.goto(CONTENT);
    await page.waitForLoadState('networkidle');
    expect(errors).toEqual([]);
  });
});
