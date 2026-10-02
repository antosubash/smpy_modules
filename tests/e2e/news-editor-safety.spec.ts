import { expect, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { clickAndConfirm, csrfHeader, login } from './helpers';

/**
 * The editor's safety nets: taking an article down, reading it in another
 * language, typing on the canvas without losing the caret, and a stale tab
 * being refused rather than silently overwriting a newer save.
 */
test.describe('News — editor safety', () => {
  test('unpublishing from the editor takes the article off the public site', async ({ page }) => {
    await login(page);
    const { articleId, slug, url } = await seedArticle(page, {
      prefix: 'safety-unpub',
      titlePrefix: 'Safety',
      publish: true,
      body: paragraphBody('Live copy.'),
    });
    expect((await page.request.get(url)).status()).toBe(200);

    await page.goto(`/admin/news/articles/${articleId}/edit`);
    await clickAndConfirm(page, page.getByRole('button', { name: /^unpublish$/i }), /^unpublish$/i);

    await expect(page.getByText('Unpublished', { exact: true })).toBeVisible();
    await expect(page.getByText(`/news/${slug} · Draft · undated`, { exact: true })).toBeVisible();
    expect((await page.request.get(url)).status()).toBe(404);
  });

  test('the language switch links across, and <html lang> follows the page', async ({ page }) => {
    await login(page);
    const en = await seedArticle(page, {
      prefix: 'safety-lang',
      titlePrefix: 'Safety',
      publish: true,
      body: paragraphBody('The English body.'),
    });
    const headers = await csrfHeader(page);
    const created = await page.request.post(`/api/news/articles/${en.articleId}/translations`, {
      headers,
      data: { locale: 'de', title: 'Sicherheit auf Deutsch' },
    });
    expect(created.status(), await created.text()).toBe(201);
    const de = (await created.json()) as { id: number };
    await page.request.put(`/api/news/articles/${de.id}/body`, {
      headers,
      data: { draft_data: paragraphBody('Der deutsche Text.') },
    });
    const published = await page.request.post(`/api/news/articles/${de.id}/publish`, {
      headers,
      data: {},
    });
    expect(published.status(), await published.text()).toBe(200);

    await page.goto(`/news/${en.slug}`);
    await expect(page.getByText('The English body.')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');

    const link = page.getByRole('link', { name: 'Deutsch' });
    await expect(link).toHaveAttribute('hreflang', 'de');
    await link.click();

    await expect(page).toHaveURL(new RegExp(`/de/news/${en.slug}$`));
    await expect(page.getByText('Der deutsche Text.')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe('de');
  });

  test('typing in a block field keeps focus, and the text autosaves', async ({ page }) => {
    await login(page);
    const { articleId } = await seedArticle(page, {
      prefix: 'safety-focus',
      body: {
        root: { props: { title: 'Focus check' } },
        content: [{ type: 'Paragraph', props: { id: 'p-1', text: 'Opening line', lead: false } }],
        zones: {},
      },
    });

    await page.goto(`/admin/news/articles/${articleId}/body`);
    const canvas = page.frameLocator('#preview-frame');
    await canvas.getByText('Opening line', { exact: true }).click();

    const text = page.getByRole('textbox', { name: 'Text' });
    await expect(text).toBeVisible();
    await text.click();
    await page.keyboard.press('End');
    await page.keyboard.type(' hello world', { delay: 50 });

    await expect(text).toHaveValue(/hello world$/);
    await expect(text).toBeFocused();

    await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 15_000 });
    await page.reload();
    await expect(page.frameLocator('#preview-frame').getByText(/hello world$/)).toBeVisible();
  });

  test('a stale tab is refused instead of overwriting a newer save', async ({ context, page }) => {
    await login(page);
    const { articleId, slug } = await seedArticle(page, {
      prefix: 'safety-stale',
      titlePrefix: 'Safety',
    });
    const other = await context.newPage();

    for (const tab of [page, other]) {
      await tab.goto(`/admin/news/articles/${articleId}/edit`);
      await expect(tab.getByLabel('Headline')).toHaveValue(`Safety ${slug}`);
    }

    await page.getByLabel('Headline').fill('Written in the first tab');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    await other.getByLabel('Headline').fill('Written in the second tab');
    await other.getByRole('button', { name: /^save$/i }).click();
    await expect(other.getByText(/changed somewhere else/i)).toBeVisible();
    await expect(other.getByRole('button', { name: 'Reload' })).toBeVisible();

    const detail = await page.request.get(`/api/news/articles?q=${slug}`);
    const listed = (await detail.json()) as { items: { title: string }[] };
    expect(listed.items[0].title).toBe('Written in the first tab');
  });
});
