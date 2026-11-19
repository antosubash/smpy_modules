// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { item } from '../page-tests/public-support';
import { flush, stubFetch } from '../page-tests/support';
import { mount, ready, settle } from '../page-tests/test-dom';
import type { PublicListItem } from '../public/types';

const page = { props: {} as Record<string, unknown> };
vi.mock('@inertiajs/react', () => ({ usePage: () => ({ props: page.props }) }));

const { UpcomingEventsBlock } = await import('./UpcomingEventsBlock');
const { UpcomingEventsRender } = await import('./UpcomingEventsRender');

const UPCOMING = 'GET /api/events/public/upcoming';
const CALENDARS = 'GET /api/events/public/calendars';
const base = {
  heading: 'Coming up',
  calendars: [],
  category: '',
  count: 5,
  layout: 'list' as const,
  showImages: true,
};

type Rendered = Parameters<typeof UpcomingEventsRender>[0];
const render = (props: Partial<Rendered> = {}) => <UpcomingEventsRender {...base} {...props} />;

beforeEach(() => {
  page.props = { locale: 'en' };
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('UpcomingEvents', () => {
  it('fetches with the page locale and the stored slugs', async () => {
    page.props = { locale: 'de' };
    const calls = stubFetch({ [UPCOMING]: { items: [item()] } });
    const view = await mount(
      render({ calendars: [{ slug: 'a' }, { slug: 'b' }], category: 'talks' }),
    );
    await ready(view, 'li');
    expect(calls[0].url).toBe(
      '/api/events/public/upcoming?calendar=a&calendar=b&category=talks&count=5&locale=de',
    );
  });

  it('renders a list: the heading, the time on the event clock and a link to the item', async () => {
    stubFetch({ [UPCOMING]: { items: [item({ title: 'Concert', url: '/events/concert' })] } });
    const view = await mount(render());
    await ready(view, 'li');
    expect(view.find('h2')?.textContent).toBe('Coming up');
    expect(view.find('a')?.getAttribute('href')).toBe('/events/concert');
    expect(view.find('time')?.getAttribute('datetime')).toBe('2026-07-06T10:00');
    expect(view.find('time')?.textContent).toContain('10:00');
  });

  it('marks a title that is not in the page language', async () => {
    page.props = { locale: 'de' };
    stubFetch({ [UPCOMING]: { items: [item({ lang: 'en', title: 'Concert' })] } });
    const view = await mount(render());
    await ready(view, 'li');
    expect(view.find('a')?.getAttribute('lang')).toBe('en');
  });

  it('renders cards, with images only when showImages is on', async () => {
    const items: PublicListItem[] = [item({ image: 'https://cdn.example.com/a.png' })];
    stubFetch({ [UPCOMING]: { items } });
    const on = await mount(render({ layout: 'cards' }));
    await ready(on, 'li');
    const img = on.find<HTMLImageElement>('img');
    expect(img?.getAttribute('src')).toBe('https://cdn.example.com/a.png');
    expect(img?.getAttribute('alt')).toBe('');
    await on.unmount();
    const off = await mount(render({ layout: 'cards', showImages: false }));
    await ready(off, 'li');
    expect(off.find('img')).toBeNull();
    await off.unmount();
    const list = await mount(render({ layout: 'list' }));
    await ready(list, 'li');
    expect(list.find('img')).toBeNull(); // images are for cards only
  });

  it('marks cancelled and rescheduled items', async () => {
    stubFetch({
      [UPCOMING]: {
        items: [item({ key: 'a', status: 'cancelled' }), item({ key: 'b', rescheduled: true })],
      },
    });
    const view = await mount(render());
    await ready(view, 'li');
    expect(view.host.textContent).toContain('Cancelled');
    expect(view.host.textContent).toContain('Rescheduled');
  });

  it('says the zone of an item the server marked, and only that one', async () => {
    stubFetch({
      [UPCOMING]: {
        items: [
          item({
            key: 'a',
            title: 'East coast reading',
            show_timezone: true,
            timezone: 'America/New_York',
          }),
          item({ key: 'b', title: 'Local reading', show_timezone: false }),
        ],
      },
    });
    const view = await mount(render());
    await ready(view, 'li');
    const times = view.all('time').map((t) => t.textContent ?? '');
    expect(times[0]).toContain('(America/New_York)');
    expect(times[1]).not.toContain('(');
  });

  it('renders text only: markup in a title stays text', async () => {
    stubFetch({ [UPCOMING]: { items: [item({ title: '<img src=x onerror=alert(1)>' })] } });
    const view = await mount(render());
    await ready(view, 'li');
    expect(view.find('img')).toBeNull();
    expect(view.host.textContent).toContain('<img src=x');
  });

  it('renders nothing while loading, when empty and on a failed fetch', async () => {
    stubFetch({ [UPCOMING]: () => new Promise(() => {}) });
    const loading = await mount(render());
    expect(loading.host.innerHTML).toBe('');
    await loading.unmount();
    stubFetch({ [UPCOMING]: { items: [] } });
    const empty = await mount(render());
    await settle();
    expect(empty.host.innerHTML).toBe('');
    await empty.unmount();
    stubFetch({ [UPCOMING]: () => new Response('no', { status: 500 }) });
    const failed = await mount(render());
    await settle();
    expect(failed.host.innerHTML).toBe('');
  });

  it('a render that throws leaves the page standing', async () => {
    stubFetch({ [UPCOMING]: { items: [{ key: 'broken' }] } });
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    const view = await mount(
      <main>
        <p>before</p>
        {render()}
        <p>after</p>
      </main>,
    );
    await settle();
    await settle();
    expect(view.host.textContent).toBe('beforeafter');
    quiet.mockRestore();
  });

  it('shows an editor-only hint for an empty answer, and none to a visitor', async () => {
    stubFetch({ [UPCOMING]: { items: [] } });
    const editing = await mount(render({ puck: { isEditing: true } } as Partial<Rendered>));
    await settle();
    await settle();
    expect(editing.host.textContent).toContain('No upcoming public events');
    await editing.unmount();
    const visitor = await mount(render());
    await settle();
    expect(visitor.host.textContent).toBe('');
  });

  it('tells the editor how many chosen calendars are not public, without naming one', async () => {
    stubFetch({
      [UPCOMING]: { items: [] },
      [CALENDARS]: {
        calendars: [
          { id: 'c1', slug: 'pub', name: 'Public one', color: '#fff', default_timezone: 'UTC' },
        ],
        categories: [],
        default_timezone: 'UTC',
      },
    });
    const view = await mount(
      render({
        calendars: [{ slug: 'pub' }, { slug: 'gone-secret' }],
        puck: { isEditing: true },
      } as Partial<Rendered>),
    );
    await flush(40);
    expect(view.host.textContent).toContain('1 chosen calendar is not public or no longer exists');
    expect(view.host.textContent).not.toContain('gone-secret');
  });

  it('clamps a stored count of 4.5 and 99', async () => {
    const calls = stubFetch({ [UPCOMING]: { items: [] } });
    for (const count of [4.5, 99]) {
      const view = await mount(render({ count }));
      await settle();
      await view.unmount();
    }
    expect(calls.map((c) => new URL(c.url, 'http://x').searchParams.get('count'))).toEqual([
      '4',
      '20',
    ]);
  });
});

describe('UpcomingEventsBlock', () => {
  const resolveFields = UpcomingEventsBlock.resolveFields as unknown as () => Promise<
    Record<
      string,
      {
        label: string;
        options?: { label: string; value: string }[];
        arrayFields?: Record<
          string,
          { label: string; options: { label: string; value: string }[] }
        >;
      }
    >
  >;

  it('builds translated selects from the anonymous route', async () => {
    stubFetch({
      [CALENDARS]: {
        calendars: [
          { id: 'c1', slug: 'team', name: 'Team', color: '#fff', default_timezone: 'UTC' },
        ],
        categories: [{ id: 'k1', slug: 'talks', name: 'Talks', color: null }],
        default_timezone: 'UTC',
      },
    });
    const fields = await resolveFields();
    expect(fields.calendars.label).toBe('Calendars');
    expect(fields.calendars.arrayFields?.slug.options.map((o) => o.value)).toEqual(['', 'team']);
    expect(fields.calendars.arrayFields?.slug.options[1].label).toBe('Team');
    expect(fields.category.options?.map((o) => o.value)).toEqual(['', 'talks']);
    expect(fields.layout.options?.map((o) => o.label)).toEqual(['List', 'Cards']);
  });

  it('has empty selects, and still its labels, when the route fails', async () => {
    stubFetch({ [CALENDARS]: () => new Response('no', { status: 500 }) });
    const fields = await resolveFields();
    expect(fields.calendars.arrayFields?.slug.options.map((o) => o.value)).toEqual(['']);
    expect(fields.heading.label).toBe('Heading');
  });

  it('normalises stored props on load, and not on every edit', () => {
    const resolveData = UpcomingEventsBlock.resolveData as unknown as (
      d: { props: Record<string, unknown> },
      p: { trigger: string },
    ) => { props: Record<string, unknown> };
    const stored = {
      ...base,
      count: 4.5,
      layout: '<b>',
      calendars: [{ slug: 'a' }, { slug: 7 }, null],
      heading: 'h'.repeat(300),
    };
    const loaded = resolveData({ props: stored }, { trigger: 'load' }).props;
    expect(loaded.count).toBe(4);
    expect(loaded.layout).toBe('list');
    expect(loaded.calendars).toEqual([{ slug: 'a' }]);
    expect((loaded.heading as string).length).toBe(200);
    expect(resolveData({ props: stored }, { trigger: 'force' }).props.count).toBe(4.5);
  });

  it('summarises a calendar row with text, never a catalogue key', () => {
    const field = (
      UpcomingEventsBlock.fields as unknown as Record<
        string,
        { getItemSummary: (i: { slug?: string }) => string }
      >
    ).calendars;
    expect(field.getItemSummary({ slug: '' })).toBe('Calendar');
    expect(field.getItemSummary({ slug: 'team' })).toBe('team');
  });

  it('keeps its labels as catalogue keys until pagebuilder resolves them', () => {
    expect(UpcomingEventsBlock.label).toBe('events.blocks.upcoming.label');
    expect((UpcomingEventsBlock.fields as Record<string, { label: string }>).heading.label).toBe(
      'events.blocks.upcoming.heading',
    );
  });
});
