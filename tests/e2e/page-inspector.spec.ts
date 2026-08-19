import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, publishWithNote, uniqueSlug } from './helpers';

/**
 * The tabbed page inspector — screen 2h.
 *
 * The SEO tab's whole point is that the fields are otherwise written blind, so
 * the preview is asserted as content rather than as markup: what matters is
 * that a writer sees the title and description they will actually get.
 */

async function openEditor(page: Page, slug: string) {
  const headers = await csrfHeader(page);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `Inspector ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  const { id } = (await created.json()) as { id: number };
  await page.goto(`/pagebuilder/${id}/edit`);
  await page.getByRole('button', { name: /^settings$/i }).click();
  return id;
}

test.describe('Page inspector', () => {
  test('opens on the Page tab and switches to SEO', async ({ page }) => {
    await login(page);
    await openEditor(page, uniqueSlug('tabs'));

    await expect(page.getByTestId('inspector-tab-page')).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByLabel('Show in header nav')).toBeVisible();

    await page.getByTestId('inspector-tab-seo').click();
    await expect(page.getByTestId('seo-preview')).toBeVisible();
  });

  test('the SEO preview follows what is typed', async ({ page }) => {
    await login(page);
    await openEditor(page, uniqueSlug('preview'));
    await page.getByTestId('inspector-tab-seo').click();

    const preview = page.getByTestId('seo-preview');
    // Blank meta title falls back to the page title — the common case.
    await expect(preview).toContainText('Inspector');

    await page.getByLabel('Meta title').fill('Grant programme 2026 — Acme Lab');
    await page.getByLabel('Meta description').fill('Applications open on 1 September.');

    await expect(preview).toContainText('Grant programme 2026 — Acme Lab');
    await expect(preview).toContainText('Applications open on 1 September.');
  });

  test('the counters warn past the limit without blocking typing', async ({ page }) => {
    await login(page);
    await openEditor(page, uniqueSlug('counter'));
    await page.getByTestId('inspector-tab-seo').click();

    const long = 'x'.repeat(200);
    await page.getByLabel('Meta description').fill(long);

    // The text is accepted in full — the limit is advisory, because search
    // engines truncate on pixel width rather than characters.
    await expect(page.getByLabel('Meta description')).toHaveValue(long);
    await expect(page.getByTestId('seo-counter').nth(1)).toContainText('200 / 155');
  });

  test('nav membership and meta title survive a save', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('save');
    const id = await openEditor(page, slug);

    await page.getByLabel('Show in header nav').check();
    await page.getByLabel('Show in footer').check();
    await page.getByTestId('inspector-tab-seo').click();
    await page.getByLabel('Meta title').fill('Saved title');
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();

    const body = await (await page.request.get(`/api/pagebuilder/pages/${id}`)).json();
    expect(body.show_in_header_nav).toBe(true);
    expect(body.show_in_footer).toBe(true);
    expect(body.meta_title).toBe('Saved title');
  });

  test('the Page tab duplicates, templates and deletes', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('actions');
    const id = await openEditor(page, slug);

    await page.getByRole('button', { name: /save as template/i }).click();
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/pagebuilder/pages/${id}`)).json()).is_template,
      )
      .toBe(true);

    await page.getByRole('button', { name: /duplicate page/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);
    const copyId = Number(page.url().match(/\/pagebuilder\/(\d+)\/edit/)?.[1]);
    expect(copyId).not.toBe(id);

    // The copy deletes to the trash rather than vanishing.
    await page.getByRole('button', { name: /^settings$/i }).click();
    await page.getByRole('button', { name: /delete page/i }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('trash for 30 days');
    await dialog.getByRole('button', { name: /^delete$/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/?(\?.*)?$/);
  });

  test('renaming the URL leaves a working redirect', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('renamed');
    const id = await openEditor(page, slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();
    await publishWithNote(page);
    expect((await page.request.get(`/p/${slug}`)).status()).toBe(200);

    const moved = `${slug}-moved`;
    await page.getByLabel('URL').fill(moved);
    // The panel says what saving will cost before it happens.
    await expect(page.getByText(new RegExp(`permanent redirect from /p/${slug}`))).toBeVisible();
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();
    await publishWithNote(page);

    const old = await page.request.get(`/p/${slug}`, { maxRedirects: 0 });
    expect(old.status()).toBe(301);
    expect(old.headers().location).toBe(`/p/${moved}`);
    expect((await page.request.get(`/p/${moved}`)).status()).toBe(200);
    void id;
  });
});
