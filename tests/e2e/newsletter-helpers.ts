/**
 * What newsletter.spec.ts needs besides the screens it drives: the settings it
 * changes and puts back (R18, D7), Mailchimp export files, an import through
 * the API, the console outbox, the e2e dispatch hook (R17) and the
 * suppression lookup (PR 6). Campaign seeding is in newsletter-campaign.ts.
 *
 * The spec runs only in CI's `E2E (newsletter)` job (playwright.config.ts,
 * E2E_NEWSLETTER=1): the dispatch hook exists only on a development or testing
 * host with Celery eager and the console transport.
 */

import { expect, type Locator, type Page } from '@playwright/test';

import { moduleCsrfHeader } from './helpers';

const API = '/api/newsletter';
const HOST_SETTINGS = '/api/settings/modules/host';

/** The newsletter settings the spec writes, and what it writes. */
export const NEWSLETTER_SETTINGS = {
  transport: 'console',
  from_address: 'news@example.org',
  from_name: 'E2E News',
  physical_address: '1 Test Street, 12345 Testville',
} as const;

type NewsletterKey = keyof typeof NEWSLETTER_SETTINGS;

/** The originals of what was changed, each recorded before its first write (D7). */
export interface Cleanup {
  newsletter?: Record<NewsletterKey, unknown>;
  host?: { had: boolean; value?: string };
}

export const csrf = (page: Page) => moduleCsrfHeader(page, '/admin/newsletter/');

export async function newsletterSettings(page: Page): Promise<Record<string, unknown>> {
  const res = await page.request.get(`${API}/settings`);
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()) as Record<string, unknown>;
}

/** The newsletter fields named in `cleanup`, read now. */
export function pick(settings: Record<string, unknown>): Record<NewsletterKey, unknown> {
  const keys = Object.keys(NEWSLETTER_SETTINGS) as NewsletterKey[];
  return Object.fromEntries(keys.map((k) => [k, settings[k]])) as Record<NewsletterKey, unknown>;
}

interface HostField {
  name: string;
  value: unknown;
  db_override: boolean;
}

async function hostPublicBaseUrl(page: Page): Promise<HostField> {
  const res = await page.request.get('/api/settings/modules');
  expect(res.ok(), await res.text()).toBeTruthy();
  const { modules } = (await res.json()) as {
    modules: { package: string; fields: HostField[] }[];
  };
  const field = modules
    .find((m) => m.package === 'host')
    ?.fields.find((f) => f.name === 'public_base_url');
  expect(field, 'expected the host public_base_url setting').toBeTruthy();
  return field as HostField;
}

/**
 * The console transport, a sender and a postal address, then the host's
 * `public_base_url` (R18). `failAfter: "newsletter"` throws between the two
 * writes, which is how the partial-setup test proves the restore.
 */
export async function configureNewsletter(
  page: Page,
  cleanup: Cleanup,
  { baseURL, failAfter }: { baseURL: string; failAfter?: 'newsletter' },
): Promise<void> {
  const headers = await csrf(page);
  cleanup.newsletter ??= pick(await newsletterSettings(page));
  const saved = await page.request.put(`${API}/settings`, {
    headers,
    data: NEWSLETTER_SETTINGS,
  });
  expect(saved.ok(), await saved.text()).toBeTruthy();
  if (failAfter === 'newsletter') throw new Error('configureNewsletter: failAfter newsletter');

  if (!cleanup.host) {
    const field = await hostPublicBaseUrl(page);
    cleanup.host = field.db_override
      ? { had: true, value: String(field.value ?? '') }
      : { had: false };
  }
  const host = await page.request.put(HOST_SETTINGS, {
    headers,
    data: { public_base_url: baseURL },
  });
  expect(host.ok(), await host.text()).toBeTruthy();
}

/** Put back exactly what `cleanup` names: one PUT, and the host field or its DELETE. */
export async function restoreSettings(page: Page, cleanup: Cleanup): Promise<void> {
  const headers = await csrf(page);
  if (cleanup.newsletter) {
    const res = await page.request.put(`${API}/settings`, {
      headers,
      data: cleanup.newsletter,
    });
    expect(res.ok(), await res.text()).toBeTruthy();
  }
  if (cleanup.host) {
    const res = cleanup.host.had
      ? await page.request.put(HOST_SETTINGS, {
          headers,
          data: { public_base_url: cleanup.host.value ?? '' },
        })
      : await page.request.delete(`${HOST_SETTINGS}/public_base_url`, { headers });
    expect(res.ok(), await res.text()).toBeTruthy();
  }
}

export interface Contact {
  email: string;
  first?: string;
  last?: string;
  tags?: string[];
}

const cell = (value: string) => `"${value.replaceAll('"', '""')}"`;

/** A Mailchimp audience export: Mailchimp quotes each tag inside the TAGS cell. */
export function mailchimpCsv(rows: Contact[]): string {
  const lines = [['Email Address', 'First Name', 'Last Name', 'TAGS'].map(cell).join(',')];
  for (const r of rows) {
    const tags = (r.tags ?? []).map((t) => `"${t}"`).join(',');
    lines.push([r.email, r.first ?? '', r.last ?? '', tags].map(cell).join(','));
  }
  return `${lines.join('\n')}\n`;
}

export interface ExportFile {
  name: string;
  csv: string;
}

export const exportFile = (name: string, rows: Contact[]): ExportFile => ({
  name,
  csv: mailchimpCsv(rows),
});

/** A count on the import's result (`<dt>` label, `<dd>` value). */
export const importCount = (page: Page, label: string): Locator =>
  page
    .locator('dl > div')
    .filter({ has: page.locator('dt', { hasText: new RegExp(`^${label}$`) }) })
    .locator('dd');

export interface ImportJob {
  id: number;
  status: string;
  created: number;
  updated: number;
  skipped: number;
  suppressed: number;
  failed: number;
}

/** Upload, apply with the suggested mapping (tags on), and wait for `done`. */
export async function importViaApi(
  page: Page,
  list: string,
  files: ExportFile[],
): Promise<ImportJob> {
  const headers = await csrf(page);
  const form = new FormData();
  form.append('list', list);
  for (const f of files) form.append('files', new Blob([f.csv], { type: 'text/csv' }), f.name);
  const staged = await page.request.post(`${API}/imports`, { headers, multipart: form });
  expect(staged.status(), await staged.text()).toBe(201);
  const { id } = (await staged.json()) as ImportJob;
  const applied = await page.request.post(`${API}/imports/${id}/apply`, { headers });
  expect(applied.status(), await applied.text()).toBe(202);
  let job: ImportJob | null = null;
  await expect
    .poll(async () => {
      job = (await (await page.request.get(`${API}/imports/${id}`)).json()) as ImportJob;
      return job.status;
    })
    .toBe('done');
  return job as unknown as ImportJob;
}

export interface OutboxMessage {
  to: string;
  subject: string;
  html: string;
  text: string;
  headers: Record<string, string>;
}

export async function outbox(page: Page): Promise<OutboxMessage[]> {
  const res = await page.request.get(`${API}/outbox`);
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()) as OutboxMessage[];
}

export interface Progress {
  status: string;
  recipients: number;
  queued: number;
  sent: number;
  suppressed: number;
}

export async function progress(page: Page, campaignId: number): Promise<Progress> {
  const res = await page.request.get(`${API}/campaigns/${campaignId}/progress`);
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()) as Progress;
}

/** Run dispatcher ticks (R17) until `predicate` holds for the progress, at most `max`. */
export async function tickUntil(
  page: Page,
  campaignId: number,
  predicate: (p: Progress) => boolean,
  max = 5,
): Promise<Progress> {
  const headers = await csrf(page);
  let last: Progress | null = null;
  for (let i = 0; i < max; i++) {
    const tick = await page.request.post(`${API}/outbox/dispatch`, { headers });
    expect(tick.ok(), await tick.text()).toBeTruthy();
    last = await progress(page, campaignId);
    if (predicate(last)) return last;
  }
  throw new Error(`tickUntil: not reached after ${max} ticks: ${JSON.stringify(last)}`);
}

export interface Suppression {
  reason: string;
  list_type_key: string;
  source: string;
}

export async function lookupSuppressions(page: Page, email: string): Promise<Suppression[]> {
  const res = await page.request.post(`${API}/suppressions/lookup`, {
    headers: await csrf(page),
    data: { email },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()) as Suppression[];
}

export interface Subscriber {
  email: string;
  status: string;
  tags: string[];
}

/** One list's subscribers matching `q`, through PR 6's search. */
export async function searchSubscribers(page: Page, list: string, q: string) {
  const res = await page.request.post(`${API}/lists/${list}/subscribers/search`, {
    headers: await csrf(page),
    data: { q },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return ((await res.json()) as { items: Subscriber[] }).items;
}
