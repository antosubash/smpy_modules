/**
 * The campaign side of newsletter.spec.ts: a body seeded through the API (the
 * suite seeds bodies rather than dragging blocks onto Puck's canvas), the
 * test-send dialog and the report screen's numbers.
 */

import { expect, type Locator, type Page } from '@playwright/test';

import { csrf } from './newsletter-helpers';

const API = '/api/newsletter';

/** Replace a draft campaign's body. */
export async function setBody(page: Page, campaignId: number, body: unknown[]): Promise<void> {
  const headers = await csrf(page);
  const current = await (await page.request.get(`${API}/campaigns/${campaignId}`)).json();
  const res = await page.request.patch(`${API}/campaigns/${campaignId}`, {
    headers,
    data: { expected_revision: current.revision, body },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

/** A card block holding the server's snapshot of article `sourceId`. */
export async function articleCard(page: Page, id: string, sourceId: number) {
  const res = await page.request.post(`${API}/cards/snapshot`, {
    headers: await csrf(page),
    data: { kind: 'article', source_id: sourceId },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return { type: 'ArticleCard', props: { ...(await res.json()), id } };
}

/** A report tile's number, under its label. */
export const reportTile = (page: Page, label: string): Locator =>
  page
    .locator('div.text-sm', { hasText: new RegExp(`^${label}$`) })
    .locator('xpath=following-sibling::div[1]');

/** Send a test from the editor's dialog; each recipient's result text, in order. */
export async function sendTest(page: Page, recipients: string[]): Promise<string[]> {
  await page.getByRole('button', { name: 'Send test' }).click();
  const dialog = page.getByRole('dialog', { name: 'Send a test email' });
  await dialog.getByLabel('Recipients').fill(recipients.join('\n'));
  await dialog.getByRole('button', { name: 'Send', exact: true }).click();
  const items = dialog.getByRole('list', { name: 'Test results' }).getByRole('listitem');
  await expect(items).toHaveCount(recipients.length);
  const texts = await items.allTextContents();
  await dialog.getByRole('button', { name: 'Close', exact: true }).first().click();
  return texts;
}
