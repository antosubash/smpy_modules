// @vitest-environment happy-dom

import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import { MARCH, pageOf } from '../page-tests/calendar-support';
import { flush, stubFetch } from '../page-tests/support';
import { act, mount } from '../page-tests/test-dom';

const page = { props: {} as Record<string, unknown> };
vi.mock('@inertiajs/react', () => ({ usePage: () => ({ props: page.props }) }));
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

const { EventsCalendarRender } = await import('./EventsCalendarRender');
const { EventsCalendarBlock } = await import('./EventsCalendarBlock');

const CALENDARS = 'GET /api/events/public/calendars';
const OCCURRENCES = 'GET /api/events/public/occurrences';
const cal = (id: string, slug: string, zone = 'Europe/Vienna') => ({
  id,
  slug,
  name: `Name of ${slug}`,
  color: '#2563eb',
  default_timezone: zone,
});
const answer = (...calendars: ReturnType<typeof cal>[]) => ({
  calendars,
  categories: [{ id: 'k1', slug: 'talks', name: 'Talks', color: null }],
  default_timezone: 'Europe/Vienna',
});
const base = {
  calendars: [{ slug: 'pub' }],
  defaultView: 'month' as const,
  height: 'medium' as const,
};

async function open(props: Record<string, unknown> = {}, routes: Record<string, unknown> = {}) {
  const calls = stubFetch({
    [CALENDARS]: answer(cal('c1', 'pub')),
    [OCCURRENCES]: pageOf([]),
    ...routes,
  });
  const view = await mount(<EventsCalendarRender {...base} {...props} />);
  await flush(40);
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush(40);
  return { view, calls };
}

beforeEach(() => {
  fakeGrid.reset();
  page.props = { locale: 'en' };
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('EventsCalendar', () => {
  it('is a read-only grid', async () => {
    await open();
    expect(fakeGrid.last).not.toBeNull();
    expect(fakeGrid.last?.editing).toBeUndefined();
  });

  it('reads the occurrences route, limited to the resolved calendars', async () => {
    const { calls } = await open(
      { calendars: [{ slug: 'pub' }, { slug: 'gone-secret' }] },
      { [CALENDARS]: answer(cal('c1', 'pub')) },
    );
    const read = calls.find((c) => c.url.startsWith('/api/events/public/occurrences'));
    expect(read).toBeDefined();
    const query = new URL(read?.url ?? '', 'http://x').searchParams;
    expect(query.getAll('calendar')).toEqual(['c1']);
    expect(calls.map((c) => c.url).join(' ')).not.toContain('gone-secret/');
    const first = calls.find((c) => c.url.startsWith('/api/events/public/calendars'));
    expect(new URL(first?.url ?? '', 'http://x').searchParams.getAll('calendar')).toEqual([
      'pub',
      'gone-secret',
    ]);
  });

  it('opens on the chosen view, and the default for a value it does not know', async () => {
    await open({ defaultView: 'week' });
    expect(fakeGrid.last?.view).toBe('week');
    document.body.innerHTML = '';
    fakeGrid.reset();
    await open({ defaultView: '<b>' });
    expect(fakeGrid.last?.view).toBe('month');
  });

  it('holds its height before and after the grid is there', async () => {
    const { view } = await open({ height: 'tall' });
    expect(view.find<HTMLElement>('[data-events-calendar]')?.style.minHeight).toBe('800px');
    const before = renderToStaticMarkup(
      EventsCalendarBlock.render({ ...base, height: 'compact' } as never),
    );
    expect(before).toContain('min-height:480px');
  });

  it('renders nothing when a chosen calendar resolves to nothing, and says why in the editor', async () => {
    const hidden = { [CALENDARS]: answer() };
    const secret = { calendars: [{ slug: 'secret-one' }] };
    const visitor = await open(secret, hidden);
    expect(visitor.view.host.innerHTML).toBe('');
    expect(fakeGrid.last).toBeNull();
    document.body.innerHTML = '';
    const editor = await open({ ...secret, puck: { isEditing: true } }, hidden);
    expect(editor.view.host.textContent).toContain(
      '1 chosen calendar is not public or no longer exists',
    );
    expect(editor.view.host.textContent).not.toContain('secret-one');
  });

  it('a selection that cannot be read renders nothing and asks for no calendars', async () => {
    for (const calendars of ['pub', ['pub'], [null], [{ slug: 7 }], {}]) {
      const { view, calls } = await open({ calendars: calendars as never });
      expect(view.host.innerHTML, JSON.stringify(calendars)).toBe('');
      expect(calls.filter((c) => c.url.includes('/public/'))).toEqual([]);
      document.body.innerHTML = '';
    }
  });

  it('renders nothing when no calendar is public, or the route fails', async () => {
    const none = await open({ calendars: [] }, { [CALENDARS]: answer() });
    expect(none.view.host.innerHTML).toBe('');
    document.body.innerHTML = '';
    const failed = await open({}, { [CALENDARS]: () => new Response('no', { status: 500 }) });
    expect(failed.view.host.innerHTML).toBe('');
  });

  it('a failing grid leaves the page standing', async () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { view } = await open({}, { [CALENDARS]: { calendars: [{ id: 'c1' }], categories: [] } });
    expect(view.host.textContent ?? '').not.toContain('undefined');
    quiet.mockRestore();
  });
});

describe('EventsCalendarBlock', () => {
  const fields = EventsCalendarBlock.fields as unknown as Record<string, { label: string }>;

  it('keeps its labels as catalogue keys until pagebuilder resolves them', () => {
    expect(EventsCalendarBlock.label).toBe('events.blocks.calendar.label');
    expect(fields.defaultView.label).toBe('events.blocks.calendar.default_view');
    expect(fields.height.label).toBe('events.blocks.calendar.height');
  });

  it('builds translated selects, with the calendars from the anonymous route', async () => {
    stubFetch({ [CALENDARS]: answer(cal('c1', 'team')) });
    const resolve = EventsCalendarBlock.resolveFields as unknown as () => Promise<
      Record<
        string,
        {
          label: string;
          options?: { label: string }[];
          arrayFields?: Record<string, { options: { value: string }[] }>;
        }
      >
    >;
    const built = await resolve();
    expect(built.calendars.label).toBe('Calendars (up to 10)');
    expect(built.calendars.arrayFields?.slug.options.map((o) => o.value)).toEqual(['', 'team']);
    expect(built.height.options?.map((o) => o.label)).toEqual(['Compact', 'Medium', 'Tall']);
  });

  it('normalises stored props on load', () => {
    const resolveData = EventsCalendarBlock.resolveData as unknown as (
      d: { props: Record<string, unknown> },
      p: { trigger: string },
    ) => { props: Record<string, unknown> };
    const loaded = resolveData(
      { props: { calendars: [{ slug: 'a' }, 3], defaultView: 'x', height: 'huge' } },
      { trigger: 'load' },
    ).props;
    // An unreadable selection is kept as it is (and shows nothing), never rewritten to "all".
    expect(loaded).toEqual({
      calendars: [{ slug: 'a' }, 3],
      defaultView: 'month',
      height: 'medium',
    });
  });
});
