// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toEventInput } from '../calendar/adapter/mapping';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import * as zones from '../calendar/time/zones';
import type { CalendarProps, OccurrenceChange } from '../calendar/types';
import {
  calendarInfo,
  fetcherOf,
  MARCH,
  occurrence,
  openCalendar,
  pageOf,
} from './calendar-support';
import { eventDetail, flush, stubFetch } from './support';
import { act, click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

const browser = (zone: string) => vi.spyOn(zones, 'browserTimeZone').mockReturnValue(zone);
beforeEach(() => {
  fakeGrid.reset();
  browser('America/New_York');
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

const toggle = (label: string) =>
  [...document.querySelectorAll('button')].find((b) =>
    b.textContent?.startsWith(label),
  ) as HTMLButtonElement;
const named = (zone: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(zone));

describe('the grid zone', () => {
  it("is the one shown calendar's zone in calendar time", async () => {
    const { view } = await openCalendar({ calendars: [calendarInfo()] });
    expect(fakeGrid.last?.timeZone).toBe('Europe/Vienna');
    await view.unmount();
  });

  it("is the tenant's zone in calendar time with several calendars shown", async () => {
    const { view } = await openCalendar({
      calendars: [
        calendarInfo(),
        calendarInfo({ id: 'c2', name: 'Board', default_timezone: 'UTC' }),
      ],
      defaultTimezone: 'Asia/Tokyo',
    });
    expect(fakeGrid.last?.timeZone).toBe('Asia/Tokyo');
    await view.unmount();
  });

  it('is the browser zone in my time, and the choice is reported for the URL', async () => {
    const onStateChange = vi.fn();
    const { view } = await openCalendar({ onStateChange });
    await click(toggle('My time'));
    expect(fakeGrid.last?.timeZone).toBe('America/New_York');
    expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ tzMode: 'mine' }));
    await click(toggle('Calendar time'));
    expect(fakeGrid.last?.timeZone).toBe('Europe/Vienna');
    await view.unmount();
  });

  it('survives a reload: my time from the initial state', async () => {
    const { view } = await openCalendar({ initialState: { tzMode: 'mine' } });
    expect(fakeGrid.last?.timeZone).toBe('America/New_York');
    expect(toggle('My time').getAttribute('aria-pressed')).toBe('true');
    await view.unmount();
  });
});

describe('the toggle', () => {
  it('names both zones and marks the active one', async () => {
    const { view } = await openCalendar();
    expect(named('Europe/Vienna')?.textContent).toContain('Calendar time');
    expect(named('America/New_York')?.textContent).toContain('My time');
    expect(named('Europe/Vienna')?.getAttribute('aria-pressed')).toBe('true');
    expect(named('America/New_York')?.getAttribute('aria-pressed')).toBe('false');
    await view.unmount();
  });

  it('says so when both are the same zone', async () => {
    browser('Europe/Vienna');
    const { view } = await openCalendar();
    expect(document.body.textContent).toContain('Your time is the same');
    await view.unmount();
  });

  it('is a labelled group', async () => {
    const { view } = await openCalendar();
    expect(
      document.querySelector('fieldset[aria-label="Time zone of the calendar"]'),
    ).not.toBeNull();
    await view.unmount();
  });
});

describe('what the zone does not touch', () => {
  it('leaves an all-day occurrence exactly as it is in both modes', async () => {
    const allDay = occurrence({
      all_day: true,
      start: '2026-03-28T23:00:00Z',
      end: '2026-03-29T23:00:00Z',
      start_date: '2026-03-29',
      end_date: '2026-03-30',
    });
    const props: Partial<CalendarProps> = { fetchOccurrences: fetcherOf(pageOf([allDay])) };
    const { view } = await openCalendar(props);
    const inCalendarTime = toEventInput(fakeGrid.last?.items[0] ?? allDay, undefined);
    await click(toggle('My time'));
    const inMyTime = toEventInput(fakeGrid.last?.items[0] ?? allDay, undefined);
    expect(inMyTime).toEqual(inCalendarTime);
    expect(inMyTime).toMatchObject({ start: '2026-03-29', end: '2026-03-30', allDay: true });
    await view.unmount();
  });

  it("shows the event's own time in the popover while the grid is in my time", async () => {
    const { view } = await openCalendar({
      initialState: { tzMode: 'mine' },
      fetchOccurrences: fetcherOf(pageOf([occurrence()])),
    });
    await act(async () => fakeGrid.open('e1:0', document.body));
    const detail = document.querySelector('[data-testid="calendar-detail"]')?.textContent ?? '';
    expect(detail).toContain('Event time in Europe/Vienna');
    expect(detail).toContain('10:00');
    await view.unmount();
  });
});

describe('a write in my time', () => {
  it("still sends the event's own wall clock", async () => {
    const calls = stubFetch({
      'GET /api/events/occurrences': { items: [occurrence()], truncated: false },
      'GET /api/events/events/e1': eventDetail({
        id: 'e1',
        revision: 7,
        starts_at: '2026-03-23T09:00:00Z',
        ends_at: '2026-03-23T10:00:00Z',
        start_local: '2026-03-23T10:00',
        end_local: '2026-03-23T11:00',
      }),
      'PATCH /api/events/events/e1': eventDetail({ id: 'e1' }),
    });
    const { ConsoleCalendar } = await import('../calendar/console/ConsoleCalendar');
    const view = await mount(
      <ConsoleCalendar
        calendars={[calendarInfo()]}
        categories={[]}
        defaultTimezone="Europe/Vienna"
        contentLocales={['en']}
        editorUrl="/admin/events/edit"
        initialState={{ tzMode: 'mine' }}
      />,
    );
    await flush();
    await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
    await flush();
    expect(fakeGrid.last?.timeZone).toBe('America/New_York');
    // Dropped on 30 March at 05:00 in the New York grid (EDT): 09:00Z, 11:00 in Vienna.
    const change: OccurrenceChange = {
      occurrence: occurrence(),
      kind: 'move',
      start: '2026-03-30T09:00:00Z',
      end: '2026-03-30T10:00:00Z',
      allDay: false,
    };
    await act(async () => {
      await fakeGrid.change(change);
    });
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      expected_revision: 7,
      times: {
        all_day: false,
        timezone: 'Europe/Vienna',
        start: '2026-03-30T11:00',
        end: '2026-03-30T12:00',
      },
    });
    await view.unmount();
  });
});
