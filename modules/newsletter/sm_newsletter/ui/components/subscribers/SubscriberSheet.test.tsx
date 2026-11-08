// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { Subscriber, SubscriberDetail, Suppression } from '../../utils/types';
import { SubscriberSheet } from './SubscriberSheet';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const subscriber: Subscriber = {
  uuid: 'u1',
  email: 'ada@example.com',
  status: 'confirmed',
  first_name: 'Ada',
  last_name: 'Lovelace',
  tags: ['vip'],
  confirmed_at: '2026-10-01T10:00:00Z',
  trashed: false,
  suppressed: false,
};
const suppression = (over: Partial<Suppression> = {}): Suppression => ({
  id: 5,
  fingerprint: 'fp5',
  reason: 'complaint',
  list_type_key: '',
  source: 'send',
  created_at: '2026-11-01T10:00:00Z',
  version: 'v5',
  liftable: true,
  block: null,
  ...over,
});
const detailOf = (
  over: Omit<Partial<SubscriberDetail>, 'subscriber'> & { subscriber?: Partial<Subscriber> } = {},
): SubscriberDetail => ({
  subscriber: { ...subscriber, ...over.subscriber },
  engagement: {
    campaigns_sent: 4,
    last_sent_at: '2026-11-02T10:00:00Z',
    last_campaign_name: 'Autumn news',
    opened_campaigns: 3,
    clicked_campaigns: 1,
  },
  suppressions: over.suppressions ?? [],
  records_url: '/admin/records/news/u1',
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

// Not 'Unsubscribed': that is also a status label.
const { unsubscribed: _, ...rest } = en.suppressions.reasons;
const REASONS = Object.values(rest);

describe('SubscriberSheet', () => {
  let root: ReturnType<typeof createRoot>;
  let detail: SubscriberDetail;
  let fetchMock: ReturnType<typeof vi.fn>;
  let unsubscribe: () => Response;
  let lift: () => Response;
  const onChanged = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    onChanged.mockReset();
    onClose.mockReset();
    detail = detailOf();
    unsubscribe = () => json(subscriber);
    lift = () => json({ id: 1 });
    fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/fields')) {
        return json([
          {
            key: 'tags',
            label: 'Tags',
            type: 'choice',
            many: true,
            choices: [
              { value: 'vip', label: 'VIP' },
              { value: 'beta', label: 'Beta' },
            ],
            system: false,
            ops: ['any'],
          },
        ]);
      }
      if (url.endsWith('/unsubscribe')) return unsubscribe();
      if (url.endsWith('/lift')) return lift();
      if (url.endsWith('/tags')) return json(subscriber);
      return json(detail);
    });
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  async function render(flags: { canEdit: boolean; canManage: boolean }) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(SubscriberSheet, {
          listKey: 'news',
          uuid: 'u1',
          onChanged,
          onClose,
          ...flags,
        }),
      ),
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
  const text = () => document.body.textContent ?? '';
  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label);
  const lastButton = (label: string) =>
    [...document.querySelectorAll('button')].filter((b) => b.textContent === label).at(-1);
  const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');

  it('canEdit alone: tag editor, no unsubscribe, no lift', async () => {
    detail = detailOf({ suppressions: [suppression()] });
    await render({ canEdit: true, canManage: false });
    expect(button(en.subscribers.detail.tags_save)).toBeDefined();
    expect(button(en.subscribers.detail.unsubscribe)).toBeUndefined();
    expect(button(en.suppressions.lift.action)).toBeUndefined();
  });

  it('canManage alone: unsubscribe and lift, read-only tags', async () => {
    detail = detailOf({ suppressions: [suppression({ reason: 'imported_cleaned' })] });
    await render({ canEdit: false, canManage: true });
    expect(button(en.subscribers.detail.tags_save)).toBeUndefined();
    expect(document.querySelectorAll('input[type=checkbox]')).toHaveLength(0);
    expect(text()).toContain('VIP');
    expect(button(en.subscribers.detail.unsubscribe)).toBeDefined();
    expect(button(en.suppressions.lift.action)).toBeDefined();
  });

  it('shows the four aggregates and no per-campaign rows', async () => {
    await render({ canEdit: false, canManage: false });
    const t = text();
    expect(t).toContain(en.subscribers.detail.engagement);
    expect(t).toContain('Autumn news');
    expect(t).toContain(en.subscribers.detail.campaigns_sent);
    expect(t).toContain(en.subscribers.detail.opened);
    expect(t).toContain(en.subscribers.detail.clicked);
    expect(t).toContain(en.report.approx.opens);
    expect(document.querySelectorAll('table')).toHaveLength(0);
  });

  it('asks before unsubscribing, then posts and reloads', async () => {
    await render({ canEdit: false, canManage: true });
    act(() => button(en.subscribers.detail.unsubscribe)?.click());
    expect(posts()).toHaveLength(0);
    await act(async () => lastButton(en.subscribers.unsubscribe_confirm.confirm)?.click());
    expect(posts().map(([u]) => u)).toEqual([
      '/api/newsletter/lists/news/subscribers/u1/unsubscribe',
    ]);
    expect(onChanged).toHaveBeenCalled();
  });

  it('sends one unsubscribe for repeated clicks and keeps the first outcome', async () => {
    let calls = 0;
    unsubscribe = () => {
      calls += 1;
      return calls === 1 ? json(subscriber) : json({ detail: 'x', code: 'not_subscribed' }, 409);
    };
    await render({ canEdit: false, canManage: true });
    act(() => button(en.subscribers.detail.unsubscribe)?.click());
    await act(async () => {
      const confirm = lastButton(en.subscribers.unsubscribe_confirm.confirm);
      for (let i = 0; i < 5; i++) confirm?.click();
    });
    expect(posts()).toHaveLength(1);
    expect(text()).not.toContain(en.errors.not_subscribed);
  });

  it('translates a 409 not_subscribed', async () => {
    unsubscribe = () => json({ detail: 'x', code: 'not_subscribed' }, 409);
    await render({ canEdit: false, canManage: true });
    act(() => button(en.subscribers.detail.unsubscribe)?.click());
    await act(async () => lastButton(en.subscribers.unsubscribe_confirm.confirm)?.click());
    expect(text()).toContain(en.errors.not_subscribed);
  });

  it('drops the last subscriber\'s error when another one opens', async () => {
    unsubscribe = () => json({ detail: 'x', code: 'not_subscribed' }, 409);
    await render({ canEdit: false, canManage: true });
    act(() => button(en.subscribers.detail.unsubscribe)?.click());
    await act(async () => lastButton(en.subscribers.unsubscribe_confirm.confirm)?.click());
    expect(text()).toContain(en.errors.not_subscribed);
    await act(async () =>
      root.render(
        createElement(SubscriberSheet, {
          listKey: 'news',
          uuid: 'u2',
          onChanged,
          onClose,
          canEdit: false,
          canManage: true,
        }),
      ),
    );
    expect(text()).not.toContain(en.errors.not_subscribed);
  });

  it('opens a hard-bounce lift with an empty email', async () => {
    detail = detailOf({ suppressions: [suppression({ reason: 'hard_bounce' })] });
    await render({ canEdit: false, canManage: true });
    act(() => button(en.suppressions.lift.action)?.click());
    const email = document.getElementById('newsletter-lift-email') as HTMLInputElement;
    expect(email).not.toBeNull();
    expect(email.value).toBe('');
  });

  it('prefills the known address for another reason', async () => {
    detail = detailOf({ suppressions: [suppression({ reason: 'imported_cleaned' })] });
    await render({ canEdit: false, canManage: true });
    act(() => button(en.suppressions.lift.action)?.click());
    expect((document.getElementById('newsletter-lift-email') as HTMLInputElement).value).toBe(
      'ada@example.com',
    );
  });

  async function liftCleaned() {
    detail = detailOf({ suppressions: [suppression({ reason: 'imported_cleaned' })] });
    await render({ canEdit: false, canManage: true });
    act(() => button(en.suppressions.lift.action)?.click());
    const note = document.getElementById('newsletter-lift-note') as HTMLTextAreaElement;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(
        note,
        'ok',
      );
      note.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button(en.suppressions.lift.confirm)?.click());
  }

  it('confirms a lift, and closes the dialog with the reason when the row changed', async () => {
    await liftCleaned();
    expect(document.querySelector('[role="status"]')?.textContent).toBe(en.suppressions.lift.done);
    act(() => root.unmount());
    lift = () => json({ detail: 'x', code: 'suppression_changed' }, 409);
    await liftCleaned();
    expect(document.getElementById('newsletter-lift-note')).toBeNull();
    expect(text()).toContain(en.errors.suppression_changed);
  });

  it('an opt_out_stands row has no lift and shows the reason', async () => {
    detail = detailOf({
      suppressions: [suppression({ reason: 'unsubscribed', block: 'opt_out_stands' })],
    });
    await render({ canEdit: false, canManage: true });
    expect(button(en.suppressions.lift.action)).toBeUndefined();
    expect(text()).toContain(en.errors.opt_out_stands);
  });

  it('a trashed subscriber has no actions', async () => {
    detail = detailOf({
      subscriber: { trashed: true },
      suppressions: [suppression({ reason: 'imported_cleaned' })],
    });
    await render({ canEdit: true, canManage: true });
    expect(text()).toContain(en.subscribers.trashed);
    expect(button(en.subscribers.detail.tags_save)).toBeUndefined();
    expect(button(en.subscribers.detail.unsubscribe)).toBeUndefined();
    expect(button(en.suppressions.lift.action)).toBeUndefined();
  });

  it('labels the flag as tenant-wide and gives no reason next to it (TL1)', async () => {
    detail = detailOf({ subscriber: { suppressed: true } });
    await render({ canEdit: false, canManage: true });
    expect(text()).toContain(en.subscribers.suppressed);
    expect(text()).toContain(en.subscribers.detail.suppressions_empty);
    for (const reason of REASONS) expect(text()).not.toContain(reason);
  });
});
