// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { button, category, eventItem, field, flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { router } = await import('@inertiajs/react');
const { default: Events } = await import('../../pages/Events');
const API = '/api/events/events';
const props = {
  content_locales: ['en', 'de'],
  can_create: true,
  categories: [category],
  calendars: [
    {
      id: 'c1',
      name: 'Team',
      color: '#2563eb',
      default_timezone: 'Europe/Vienna',
      can_write_events: true,
    },
    {
      id: 'c2',
      name: 'Public',
      color: '#16a34a',
      default_timezone: 'UTC',
      can_write_events: false,
    },
  ],
};
const page = (items: unknown[], total = items.length, n = 1) => ({
  items,
  total,
  page: n,
  page_size: 50,
});

beforeEach(() => history.replaceState(null, '', '/admin/events/list'));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const rowOf = (view: { host: HTMLElement }, title: string) =>
  [...view.host.querySelectorAll('tr')].find((r) => r.textContent?.includes(title));

describe('Events list', () => {
  it("mirrors its filters into the address without dropping Inertia's history state", async () => {
    // Inertia keeps the page it will restore on Back in `history.state`; a `null` here made a
    // Back from the editor to this list stay on the editor (a race the leave-guard e2e hit).
    const state = { page: { component: 'Events/Events', url: '/admin/events/list' } };
    history.replaceState(state, '', '/admin/events/list');
    stubFetch({ [`GET ${API}`]: page([eventItem({ id: 'a', title: 'Draft one' })]) });
    const view = await mount(<Events {...props} />);
    await flush();
    await setValue(field('filter-status'), 'published');
    await flush();
    expect(history.state).toEqual(state);
    await view.unmount();
  });

  it('renders rows with status and scheduled badges', async () => {
    stubFetch({
      [`GET ${API}`]: page([
        eventItem({ id: 'a', title: 'Draft one' }),
        eventItem({ id: 'b', title: 'Live one', status: 'published', locked: true }),
        eventItem({
          id: 'c',
          title: 'Planned',
          scheduled: true,
          publish_at: '2026-08-01T07:00:00Z',
        }),
        eventItem({ id: 'd', title: 'Called off', cancelled: true }),
        eventItem({ id: 'e', title: 'Weekly', rrule: 'FREQ=WEEKLY;BYDAY=WE' }),
      ]),
    });
    const view = await mount(<Events {...props} />);
    await flush();
    expect(rowOf(view, 'Draft one')?.textContent).toContain('Draft');
    expect(rowOf(view, 'Live one')?.textContent).toContain('Published');
    expect(rowOf(view, 'Planned')?.textContent).toContain('Scheduled');
    expect(rowOf(view, 'Called off')?.textContent).toContain('Cancelled');
    expect(rowOf(view, 'Concert') ?? rowOf(view, 'Draft one')?.textContent).toContain('Team');
    expect(rowOf(view, 'Draft one')?.textContent).toContain('1 Jul 2026, 10:00');
    expect(rowOf(view, 'Draft one')?.textContent).toContain('Pacific/Auckland');
    expect(view.find('[aria-label^="Repeats: Every week on"]')).not.toBeNull();
    await view.unmount();
  });

  it('filters write to the query and refetch', async () => {
    const calls = stubFetch({ [`GET ${API}`]: page([]) });
    const view = await mount(<Events {...props} />);
    await flush();
    await setValue(field('filter-status'), 'published');
    await flush();
    await setValue(field('filter-calendar'), 'c1');
    await flush();
    await setValue(field('filter-category'), 'k1');
    await setValue(field('filter-from'), '2026-07-01');
    await flush();
    const last = new URL(calls.at(-1)?.url ?? '', 'http://x').searchParams;
    expect(last.get('status')).toBe('published');
    expect(last.get('calendar')).toBe('c1');
    expect(last.get('category')).toBe('k1');
    expect(last.get('from')).toMatch(/^2026-0[67]-\d\dT\d\d:00:00\.000Z$/);
    expect(location.search).toContain('status=published');
    expect(location.search).toContain('calendar=c1');
    await view.unmount();
  });

  it('starts from the filters in the URL', async () => {
    history.replaceState(null, '', '/admin/events/list?status=draft&q=jazz&page=2');
    const calls = stubFetch({ [`GET ${API}`]: page([], 120, 2) });
    const view = await mount(<Events {...props} />);
    await flush();
    const first = new URL(calls[0]?.url ?? '', 'http://x').searchParams;
    expect([first.get('status'), first.get('q'), first.get('page')]).toEqual([
      'draft',
      'jazz',
      '2',
    ]);
    expect(field('filter-text').value).toBe('jazz');
    await view.unmount();
  });

  it('text filter is debounced', async () => {
    const calls = stubFetch({ [`GET ${API}`]: page([]) });
    const view = await mount(<Events {...props} />);
    await flush();
    const before = calls.length;
    await setValue(field('filter-text'), 'ja');
    await setValue(field('filter-text'), 'jazz');
    await flush(50);
    expect(calls.length).toBe(before);
    await flush(400);
    expect(calls.length).toBe(before + 1);
    expect(new URL(calls.at(-1)?.url ?? '', 'http://x').searchParams.get('q')).toBe('jazz');
    await view.unmount();
  });

  it('pages through the total', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: (call: { url: string }) =>
        page(
          [eventItem()],
          120,
          Number(new URL(call.url, 'http://x').searchParams.get('page') ?? 1),
        ),
    });
    const view = await mount(<Events {...props} />);
    await flush();
    expect(view.host.textContent).toContain('Page 1 of 3');
    expect(view.host.textContent).toContain('120 events');
    expect(view.button('Previous page')?.hasAttribute('disabled')).toBe(true);
    await click(view.button('Next page'));
    await flush();
    expect(new URL(calls.at(-1)?.url ?? '', 'http://x').searchParams.get('page')).toBe('2');
    expect(view.host.textContent).toContain('Page 2 of 3');
    await view.unmount();
  });

  it('hides New event without can_create and offers only writable calendars', async () => {
    stubFetch({ [`GET ${API}`]: page([]) });
    const view = await mount(<Events {...props} can_create={false} />);
    await flush();
    expect(view.button('New event')).toBeUndefined();
    await view.unmount();
    const other = await mount(<Events {...props} />);
    await flush();
    await click(other.button('New event'));
    expect(vi.mocked(router.visit)).toHaveBeenCalledWith('/admin/events/edit/new?calendar=c1');
    await other.unmount();
  });

  it('offers actions only where the API allows them', async () => {
    stubFetch({
      [`GET ${API}`]: page([
        eventItem({ id: 'a', title: 'Mine' }),
        eventItem({ id: 'b', title: 'Readonly', can_write: false }),
        eventItem({ id: 'c', title: 'Locked', status: 'published', locked: true }),
        eventItem({
          id: 'd',
          title: 'Lockedpub',
          status: 'published',
          locked: true,
          can_publish: true,
        }),
      ]),
    });
    const view = await mount(<Events {...props} />);
    await flush();
    const has = (title: string) =>
      rowOf(view, title)?.querySelector('[aria-label^="Move"]') !== null;
    expect([has('Mine'), has('Readonly'), has('Locked'), has('Lockedpub')]).toEqual([
      true,
      false,
      false,
      true,
    ]);
    await view.unmount();
  });

  it('trash then restore sends expected_revision', async () => {
    let trashed = false;
    const calls = stubFetch({
      [`GET ${API}`]: (call: { url: string }) =>
        new URL(call.url, 'http://x').searchParams.get('trashed') === 'true'
          ? page(trashed ? [eventItem({ trashed: true, is_deleted: true })] : [])
          : page(trashed ? [] : [eventItem()]),
      [`DELETE ${API}/e1`]: () => {
        trashed = true;
        return null;
      },
      [`POST ${API}/e1/restore`]: () => {
        trashed = false;
        return eventItem();
      },
    });
    const view = await mount(<Events {...props} />);
    await flush();
    await click(view.find('[aria-label="Move Concert to trash"]'));
    await click(
      button('Move to trash', document.querySelector('[role="alertdialog"]') ?? document),
    );
    await flush();
    expect(
      calls.some((c) => c.method === 'DELETE' && c.url === `${API}/e1?expected_revision=4`),
    ).toBe(true);
    await click(view.button('Trash'));
    await flush();
    await click(view.find('[aria-label="Restore Concert"]'));
    await flush();
    const restore = calls.find((c) => c.url === `${API}/e1/restore`);
    expect(restore?.body).toEqual({ expected_revision: 4 });
    await view.unmount();
  });

  it('fallback title shows lang badge', async () => {
    stubFetch({
      [`GET ${API}`]: page([
        eventItem({ id: 'a', title: 'Konzert', lang: 'de' }),
        eventItem({ id: 'b', title: 'Concert', lang: 'en' }),
      ]),
    });
    const view = await mount(<Events {...props} />);
    await flush();
    expect(rowOf(view, 'Konzert')?.querySelector('[aria-label*="de version"]')).not.toBeNull();
    expect(rowOf(view, 'Concert')?.querySelector('[aria-label*="version"]')).toBeNull();
    await view.unmount();
  });

  it('shows an error without an empty-state text, and rate limits', async () => {
    stubFetch({ [`GET ${API}`]: () => Response.json({ detail: 'x', code: 'x' }, { status: 500 }) });
    const view = await mount(<Events {...props} />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('The request failed');
    expect(view.host.textContent).not.toContain('No events match');
    await view.unmount();
    vi.unstubAllGlobals();
    stubFetch({
      [`GET ${API}`]: () =>
        Response.json({ detail: 'slow', code: 'rate_limited', retry_after: 7 }, { status: 429 }),
    });
    const limited = await mount(<Events {...props} />);
    await flush();
    expect(limited.find('[role="alert"]')?.textContent).toContain('Too many');
    expect(limited.host.textContent).not.toContain('No events match');
    await limited.unmount();
  });

  it('says the list is empty only when it loaded and is', async () => {
    stubFetch({ [`GET ${API}`]: page([]) });
    const view = await mount(<Events {...props} />);
    await flush();
    expect(view.host.textContent).toContain('No events match these filters.');
    await view.unmount();
  });
});
