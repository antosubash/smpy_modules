// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import Subscribers from '../../../pages/Subscribers';
import { SEARCH_DEBOUNCE_MS } from '../../hooks/useCampaignList';

const router = vi.hoisted(() => ({ visit: vi.fn(), get: vi.fn(), post: vi.fn() }));
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  router,
  usePage: () => ({ props: { can_edit: true, can_manage: true } }),
  Link: ({ href, children, ...rest }: { href: string; children: unknown }) =>
    createElement('a', { href, ...rest }, children as never),
}));
vi.mock('@simple-module-py/ui/components/PageShell', () => ({
  PageShell: ({ children }: { children: unknown }) => createElement('div', null, children as never),
}));
vi.mock('@simple-module-py/ui/layouts/AuthenticatedLayout', () => ({
  AuthenticatedLayout: () => null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const row = (over = {}) => ({
  uuid: 'u1',
  email: 'ada@example.com',
  status: 'confirmed',
  first_name: 'Ada',
  last_name: 'Lovelace',
  tags: ['vip'],
  confirmed_at: '2026-10-01T10:00:00Z',
  trashed: false,
  suppressed: false,
  ...over,
});

describe('Subscribers page', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  let items: unknown[];

  beforeEach(() => {
    items = [row(), row({ uuid: 'u2', email: 'bo@example.com', suppressed: true })];
    fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/lists')) return json(['news']);
      if (url.endsWith('/fields')) return json([]);
      if (url.includes('/segments')) return json([]);
      return json({
        items,
        total: items.length,
        counts: { pending: 0, confirmed: 2, unsubscribed: 0 },
        records_url: '/admin/records/news',
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    router.visit.mockReset();
    router.get.mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  async function render() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(Subscribers)));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }

  it('typing a search never navigates and never touches the location (C5)', async () => {
    const before = window.location.href;
    const historyLength = window.history.length;
    await render();
    const input = document.querySelector(
      `[aria-label="${en.subscribers.search_label}"]`,
    ) as HTMLInputElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
      set?.call(input, 'ada@example.com');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, SEARCH_DEBOUNCE_MS + 100));
    });
    expect(router.visit).not.toHaveBeenCalled();
    expect(router.get).not.toHaveBeenCalled();
    expect(window.location.href).toBe(before);
    expect(window.history.length).toBe(historyLength);
    const search = fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/subscribers/search'));
    expect(search.length).toBeGreaterThan(0);
    expect(search.every(([u]) => !String(u).includes('ada'))).toBe(true);
    expect(JSON.parse(String(search.at(-1)?.[1].body)).q).toBe('ada@example.com');
  });

  it('the suppressed badge reads the tenant-wide label and shows no reason (TL1)', async () => {
    await render();
    const text = document.body.textContent ?? '';
    expect(text).toContain('ada@example.com');
    expect(text).toContain(en.subscribers.suppressed);
    const { unsubscribed: _, ...rest } = en.suppressions.reasons; // 'Unsubscribed' is also a status tab
    for (const reason of Object.values(rest)) expect(text).not.toContain(reason);
    expect(en.subscribers.suppressed).toBe("Won't receive newsletters");
  });

  it('links to the records screen', async () => {
    await render();
    const link = [...document.querySelectorAll('a')].find(
      (a) => a.textContent === en.subscribers.open_in_records,
    );
    expect(link?.getAttribute('href')).toBe('/admin/records/news');
  });
});
