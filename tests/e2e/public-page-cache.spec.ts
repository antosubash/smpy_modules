import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * #94: a published page is not the same bytes for every visitor.
 *
 * The chrome renders in the visitor's UI language and, signed in, carries who
 * they are. The Python suites pin the headers; what only a browser shows is
 * the symptom QA hit — switch language, land back on the same URL, and get the
 * page you had before, because the browser revalidated and the server said
 * "304, nothing changed".
 */

/** A header with the language switcher, or none. The layout is site-wide. */
async function putHeader(page: Page, headers: Record<string, string>, on: boolean) {
  const slot = (block: unknown) => ({ root: { props: {} }, zones: {}, content: on ? [block] : [] });
  const response = await page.request.put('/api/pagebuilder/layout', {
    headers,
    data: {
      header_data: slot({
        type: 'SiteHeader',
        props: {
          id: 'hdr',
          logoUrl: '',
          logoAlt: 'E2E Site',
          homeHref: '/p/home',
          utilityLinks: [],
          navItems: [],
          ctaLabel: '',
          ctaHref: '',
          showLocaleSwitcher: true,
          sticky: false,
        },
      }),
      footer_data: { root: { props: {} }, zones: {}, content: [] },
      note: 'e2e public page cache',
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test.describe('Public page cache', () => {
  // Put the layout back so later specs do not inherit this header.
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await putHeader(page, await moduleCsrfHeader(page, '/pagebuilder/'), false);
    await page.close();
  });

  test('switching language is seen at once, not after the cache expires (#94)', async ({
    browser,
    page,
  }) => {
    await login(page);
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    await putHeader(page, headers, true);
    const slug = uniqueSlug('e2e-relang');
    const draft = {
      root: { props: { title: 'Relang' } },
      content: [{ type: 'Text', props: { id: 't1', text: 'Body.', size: 'lg', align: 'left' } }],
      zones: {},
    };
    const created = await (
      await page.request.post('/api/pagebuilder/pages', {
        headers,
        data: { title: 'Relang', slug, draft_data: draft },
      })
    ).json();
    await page.request.post(`/api/pagebuilder/pages/${created.id}/publish`, { headers, data: {} });

    // An anonymous reader: their copy is the `public, max-age` one.
    const anon = await browser.newContext({ baseURL: new URL(page.url()).origin });
    const reader = await anon.newPage();
    await reader.goto(`/p/${slug}`);
    const header = reader.getByTestId('site-header');
    await expect(header.getByRole('button', { name: 'Change language' })).toBeVisible();

    // Submit what the switcher submits, as a real navigation, so the browser's
    // own HTTP cache is in play when the 303 lands back on the same URL.
    await Promise.all([
      reader.waitForResponse(
        (r) => r.url().endsWith(`/p/${slug}`) && r.request().method() === 'GET',
      ),
      reader.evaluate(() => {
        const form = Object.assign(document.createElement('form'), {
          method: 'post',
          action: '/i18n/set-locale',
        });
        form.append(
          Object.assign(document.createElement('input'), { name: 'locale', value: 'de' }),
        );
        document.body.append(form);
        form.submit();
      }),
    ]);
    await expect(header.getByRole('button', { name: 'Sprache ändern' })).toBeVisible();
    await anon.close();
  });
});
