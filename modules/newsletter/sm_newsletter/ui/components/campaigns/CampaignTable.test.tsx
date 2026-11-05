// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { CampaignListItem } from '../../utils/types';
import { CampaignTable } from './CampaignTable';

vi.mock('@inertiajs/react', () => ({
  Link: ({ href, children, ...rest }: { href: string; children: unknown }) =>
    createElement('a', { href, ...rest }, children as never),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const item = (over: Partial<CampaignListItem> = {}): CampaignListItem => ({
  id: 7,
  name: 'Spring',
  subject: 'Hello',
  status: 'sent',
  list_type_key: 'news',
  revision: 1,
  updated_at: null,
  recipient_count: 220,
  sent_count: 200,
  started_at: '2026-11-01T10:00:00Z',
  finished_at: null,
  opens_unique_accepted: 50,
  clicks_unique_accepted: 10,
  ...over,
});

describe('CampaignTable', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(items: CampaignListItem[], canEdit = true) {
    const host = document.body.appendChild(document.createElement('div'));
    root = createRoot(host);
    await act(async () =>
      root.render(createElement(CampaignTable, { items, canEdit, onDeleted: vi.fn() })),
    );
    return host;
  }

  it('shows open and click rates and a report link for a sent campaign', async () => {
    const host = await render([item()]);
    const cells = [...host.querySelectorAll('td')].map((c) => c.textContent);
    expect(cells).toContain('25.0%');
    expect(cells).toContain('5.0%');
    const link = host.querySelector(`a[href="/admin/newsletter/campaigns/7/report"]`);
    expect(link).not.toBeNull();
    expect(link?.textContent).toContain(en.campaigns.report_link);
    expect(link?.textContent).toContain('Report for Spring');
  });

  it('shows a dash for a draft and offers no report', async () => {
    const host = await render([
      item({ status: 'draft', sent_count: 0, started_at: null, opens_unique_accepted: 0 }),
    ]);
    expect([...host.querySelectorAll('td')].filter((c) => c.textContent === '—')).toHaveLength(2);
    expect(host.querySelector('a[href$="/report"]')).toBeNull();
  });

  it('offers Delete only for drafts, to editors', async () => {
    const drafts = [item({ status: 'draft', started_at: null }), item({ id: 8 })];
    let host = await render(drafts);
    const deletes = (h: HTMLElement) =>
      [...h.querySelectorAll('button')].filter((b) => b.textContent?.includes('Delete'));
    expect(deletes(host)).toHaveLength(1);
    act(() => root.unmount());
    document.body.innerHTML = '';
    host = await render(drafts, false);
    expect(deletes(host)).toHaveLength(0);
  });

  it('still shows Report to a viewer', async () => {
    const host = await render([item()], false);
    expect(host.querySelector('a[href$="/campaigns/7/report"]')).not.toBeNull();
  });
});
