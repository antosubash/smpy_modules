import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';
import {
  apiCreateType,
  apiDeleteType,
  apiListRecords,
  type Json,
  uniqueTypeKey,
} from './records-api';

/**
 * The `RecordForm` block (#101, part 4): a visitor sends a contact form and
 * signs up to a newsletter from a published page, end to end — the block
 * fetches the type's live definition, the submission lands as a record of
 * that type, and a signup as a pending subscriber.
 *
 * Stands alone (CLAUDE.md): it seeds its own types and pages over the APIs,
 * as `records-widget.spec.ts` builds its pages — nothing here tests Puck's
 * drag and drop. The server refuses a form sent within
 * `public_submissions_min_fill_seconds` (3 s) of loading it, so the visitor
 * waits that long, as a person would.
 */

const MIN_FILL_MS = 3_500;

async function publishPage(page: Page, slug: string, props: Json): Promise<void> {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const draftData = {
    root: { props: { title: `Form ${slug}`, width: 'full' } },
    content: [
      {
        type: 'RecordForm',
        props: {
          id: 'RecordForm-e2e',
          title: '',
          intro: '',
          submitLabel: '',
          successTitle: '',
          successBody: '',
          labels: [],
          kindHint: '',
          ...props,
        },
      },
    ],
  };
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title: `Form ${slug}`, slug, draft_data: draftData },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: number };
  await expect
    .poll(async () => (await page.request.get(`/api/pagebuilder/pages/${id}`)).status())
    .toBe(200);
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
  expect(published.status(), await published.text()).toBe(200);
}

function field(key: string, type: string, extra: Json = {}): Json {
  return { key, type, label: key[0].toUpperCase() + key.slice(1), indexed: false, ...extra };
}

test.describe('Records — the website form block', () => {
  test('a visitor sends a contact form from a published page', async ({ page, browser }) => {
    await login(page);
    const key = uniqueTypeKey('contactblk');
    await apiCreateType(page, {
      key,
      label: `Contact ${key}`,
      fields: [
        field('name', 'text', { required: true }),
        field('email', 'email', { required: true }),
        field('message', 'longtext', { required: true }),
      ],
      public_submissions: {
        kind: 'form',
        enabled: true,
        public_fields: ['name', 'email', 'message'],
        consent: { required: true, text: { en: 'You may reply to me by email.' } },
      },
    });
    const slug = uniqueSlug('records-form');
    await publishPage(page, slug, {
      typeKey: key,
      title: 'Write to us',
      successBody: 'We will get back to you.',
      labels: [{ field: 'message', label: 'Your message', help: '' }],
    });

    const anon = await browser.newContext();
    try {
      const visitor = await anon.newPage();
      await visitor.goto(`/p/${slug}`);
      await expect(visitor.getByRole('heading', { name: 'Write to us' })).toBeVisible();
      // Sending empty is refused in the browser, field by field.
      await visitor.getByRole('button', { name: 'Send' }).click();
      await expect(visitor.getByTestId('records-form-problem')).toContainText(
        'Please check the highlighted fields.',
      );
      await expect(visitor.getByLabel(/^Name/)).toHaveAttribute('aria-invalid', 'true');
      await expect(visitor.getByLabel(/^Name/)).toBeFocused();

      await visitor.getByLabel(/^Name/).fill('Ada Lovelace');
      await visitor.getByLabel(/^Email/).fill('Ada@Example.org');
      // The page's own label replaces the type's.
      await visitor.getByLabel(/^Your message/).fill('Hello from the website.');
      await visitor.getByLabel('You may reply to me by email.').check();
      await visitor.waitForTimeout(MIN_FILL_MS);
      const sent = visitor.waitForResponse((res) => res.url().endsWith(`/${key}/submit`));
      await visitor.getByRole('button', { name: 'Send' }).click();
      expect((await sent).status()).toBe(202);
      await expect(visitor.getByTestId('records-form-success')).toContainText(
        'We will get back to you.',
      );
    } finally {
      await anon.close();
    }

    await expect.poll(async () => (await apiListRecords(page, key)).items.length).toBe(1);
    const [record] = (await apiListRecords(page, key)).items;
    expect(record.status).toBe('draft');
    expect(record.data).toMatchObject({
      name: 'Ada Lovelace',
      email: 'ada@example.org',
      message: 'Hello from the website.',
      sm_source_block: 'RecordForm-e2e',
      sm_consent_text: 'You may reply to me by email.',
    });
    expect(String(record.data.sm_source_page)).toContain(`/p/${slug}`);

    // The admin sees it, with the system fields read-only.
    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await expect(page.getByTestId('records-submission-details')).toContainText(`/p/${slug}`);
    await apiDeleteType(page, key, 1);
  });

  test('a visitor signs up to a newsletter and is pending', async ({ page, browser }) => {
    await login(page);
    const key = uniqueTypeKey('newsblk');
    await apiCreateType(page, {
      key,
      label: `News ${key}`,
      fields: [],
      public_submissions: { kind: 'subscription', enabled: true, public_fields: [] },
    });
    const slug = uniqueSlug('records-signup');
    await publishPage(page, slug, { typeKey: key, title: 'Stay in touch' });

    const anon = await browser.newContext();
    try {
      const visitor = await anon.newPage();
      await visitor.goto(`/p/${slug}`);
      const email = visitor.getByLabel(/^Email/);
      await expect(email).toBeVisible();
      await email.fill('reader@example.org');
      await visitor.waitForTimeout(MIN_FILL_MS);
      await visitor.getByRole('button', { name: 'Subscribe' }).click();
      await expect(visitor.getByTestId('records-form-success')).toContainText(
        'confirm your subscription',
      );
    } finally {
      await anon.close();
    }

    await expect.poll(async () => (await apiListRecords(page, key)).items.length).toBe(1);
    const [subscriber] = (await apiListRecords(page, key)).items;
    expect(subscriber.data).toMatchObject({ sm_email: 'reader@example.org', sm_status: 'pending' });
    await apiDeleteType(page, key, 1);
  });

  test('a form that is switched off shows as unavailable', async ({ page, browser }) => {
    await login(page);
    const key = uniqueTypeKey('offblk');
    await apiCreateType(page, {
      key,
      label: `Off ${key}`,
      fields: [field('name', 'text')],
      public_submissions: { kind: 'form', enabled: false, public_fields: ['name'] },
    });
    const slug = uniqueSlug('records-form-off');
    await publishPage(page, slug, { typeKey: key });
    const anon = await browser.newContext();
    try {
      const visitor = await anon.newPage();
      await visitor.goto(`/p/${slug}`);
      await expect(visitor.getByTestId('records-form-unavailable')).toBeVisible();
      await expect(visitor.getByRole('button', { name: 'Send' })).toHaveCount(0);
    } finally {
      await anon.close();
    }
    await apiDeleteType(page, key, 0);
  });
});
