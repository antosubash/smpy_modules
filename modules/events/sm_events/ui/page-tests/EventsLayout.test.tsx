// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { category, eventItem, flush, stubFetch } from './support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { default: Events } = await import('../../pages/Events');
const API = '/api/events/events';
const props = {
  content_locales: ['en', 'de'],
  can_create: true,
  categories: [category],
  calendars: ['c1', 'c2'].map((id) => ({
    id,
    name: id,
    color: '#2563eb',
    default_timezone: 'UTC',
    can_write_events: true,
  })),
};
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 50 });
const rowOf = (view: { host: HTMLElement }, title: string) =>
  [...view.host.querySelectorAll('tr')].find((r) => r.textContent?.includes(title));

beforeEach(() => history.replaceState(null, '', '/admin/events/list'));
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

describe('Events list on a narrow screen', () => {
  it('keeps the table in its own scroll container and lets the bars wrap', async () => {
    stubFetch({
      [`GET ${API}`]: page([eventItem({ id: 'a', title: 'x'.repeat(120) })]),
    });
    const view = await mount(<Events {...props} />);
    await flush();
    const table = view.host.querySelector('table');
    // The table scrolls on its own, so it never widens the page.
    expect(table?.closest('.overflow-x-auto')).not.toBeNull();
    // Long names wrap inside their cell; the action buttons stay in one line.
    expect(rowOf(view, 'xxxx')?.querySelector('td')?.className).toContain('overflow-wrap:anywhere');
    expect(rowOf(view, 'xxxx')?.querySelector('td:last-child > div')?.className).toContain(
      'whitespace-nowrap',
    );
    // Both filter bars and the header actions wrap instead of overflowing.
    const bars = [...view.host.querySelectorAll('fieldset')];
    expect(bars).toHaveLength(2);
    for (const bar of bars) expect(bar.className).toContain('flex-wrap');
    expect(view.button('New event')?.closest('.flex-wrap')).not.toBeNull();
    await view.unmount();
  });
});
