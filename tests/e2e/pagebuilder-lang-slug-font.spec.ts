import { expect, type Page, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * Three findings from the QA of #132, end to end.
 *
 * - #187: a German page is served as a German document. The module suite
 *   asserts the rewrite on the server; this is the attribute a screen reader
 *   actually reads, after the client has mounted.
 * - #188: an invalid slug is explained in a sentence, and the editor's font
 *   comes from this origin, so the console's CSP has nothing to block. News'
 *   article body editor loaded Puck's stylesheet the same way, so it is
 *   checked too.
 */

const EMPTY = { root: { props: { title: 'x', width: 'full' } }, content: [], zones: {} };

async function createPage(page: Page, slug: string) {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title: `Lang ${slug}`, slug, draft_data: EMPTY },
  });
  expect(created.status(), await created.text()).toBe(201);
  return { headers, id: ((await created.json()) as { id: number }).id };
}

test.describe('Public pages carry their language (#187)', () => {
  test('lang="de" on /de/p/<slug>, lang="en" on /p/<slug>', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('e2e-html-lang');
    const { headers, id } = await createPage(page, slug);
    const translated = await page.request.post(`/api/pagebuilder/pages/${id}/translations`, {
      headers,
      data: { locale: 'de', title: 'Über uns' },
    });
    expect(translated.status(), await translated.text()).toBe(201);
    const de = (await translated.json()) as { id: number };
    for (const pageId of [id, de.id]) {
      const published = await page.request.post(`/api/pagebuilder/pages/${pageId}/publish`, {
        headers,
        data: {},
      });
      expect(published.status(), await published.text()).toBe(200);
    }

    // The document as served, before any script runs.
    const served = await page.request.get(`/de/p/${slug}`);
    expect(await served.text()).toContain('<html lang="de"');

    await page.goto(`/de/p/${slug}`);
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');

    await page.goto(`/p/${slug}`);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  });
});

test.describe('Page editor (#188)', () => {
  test('an invalid slug is explained, not quoted as a regex', async ({ page }) => {
    await login(page);
    const { id } = await createPage(page, uniqueSlug('e2e-slug'));
    await page.goto(`/pagebuilder/${id}/edit`);
    await page.getByRole('button', { name: /^settings$/i }).click();

    const field = page.locator('#page-settings-slug');
    await field.fill('Not A Slug!');

    const error = page.getByTestId('slug-error');
    await expect(error).toHaveText(
      'Use only lowercase letters (a–z), digits (0–9) and hyphens, starting with a letter or digit.',
    );
    await expect(field).toHaveAttribute('aria-invalid', 'true');
    // Whatever the autosave reports, it is not pydantic's wording.
    await expect(page.getByText(/should match pattern/i)).toHaveCount(0);

    await field.fill('a-valid-slug');
    await expect(error).toHaveCount(0);
  });

  /** Open an editor and assert Inter loaded from this bundle without a CSP report. */
  async function expectSelfHostedInter(page: Page, open: () => Promise<void>) {
    const violations: string[] = [];
    const external: string[] = [];
    page.on('console', (m) => {
      if (m.type() === 'error' && /content security policy/i.test(m.text())) {
        violations.push(m.text());
      }
    });
    page.on('request', (r) => {
      if (/rsms\.me|inter\.css/.test(r.url())) external.push(r.url());
    });

    await open();

    const loaded = await page.evaluate(async () => {
      await document.fonts.load('16px "Inter Variable"');
      await document.fonts.ready;
      return document.fonts.check('16px "Inter Variable"');
    });
    expect(loaded).toBe(true);
    expect(external).toEqual([]);
    expect(violations).toEqual([]);
  }

  test('the page editor loads Inter from this origin, with no CSP violation', async ({ page }) => {
    await login(page);
    const { id } = await createPage(page, uniqueSlug('e2e-font'));
    await expectSelfHostedInter(page, async () => {
      await page.goto(`/pagebuilder/${id}/edit`);
      await expect(page.getByRole('button', { name: /^settings$/i })).toBeVisible();
    });
  });

  test("news' article body editor does too", async ({ page }) => {
    await login(page);
    const { articleId } = await seedArticle(page, { prefix: 'e2e-font' });
    await expectSelfHostedInter(page, async () => {
      await page.goto(`/admin/news/articles/${articleId}/body`);
      await expect(page.locator('#preview-frame')).toBeVisible();
    });
  });
});
