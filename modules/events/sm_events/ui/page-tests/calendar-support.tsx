/** Fixtures for the `Calendar` shell tests: occurrences, calendars and a fetcher. */
import { vi } from 'vitest';
import { fakeGrid } from '../calendar/test-support/FakeGrid';
import type {
  CalendarInfo,
  CalendarProps,
  OccurrenceFetcher,
  OccurrencePage,
} from '../calendar/types';
import type { Occurrence } from '../utils/types-events';
import { flush } from './support';
import { act, mount } from './test-dom';

export function occurrence(overrides: Partial<Occurrence> = {}): Occurrence {
  return {
    source: 'events',
    key: 'e1:0',
    calendar_id: 'c1',
    start: '2026-03-23T09:00:00Z',
    end: '2026-03-23T10:00:00Z',
    all_day: false,
    timezone: 'Europe/Vienna',
    start_date: null,
    end_date: null,
    title: 'Planning',
    lang: 'en',
    color: '#2563eb',
    url: '/admin/events/edit/e1',
    status: 'confirmed',
    type: 'event',
    editable: true,
    event_id: 'e1',
    original_start: null,
    event_status: 'published',
    ...overrides,
  };
}

export function calendarInfo(overrides: Partial<CalendarInfo> = {}): CalendarInfo {
  return {
    id: 'c1',
    name: 'Team',
    color: '#2563eb',
    visibility: 'internal',
    default_timezone: 'Europe/Vienna',
    can_write_events: true,
    ...overrides,
  };
}

export const MARCH = {
  start: '2026-02-23T00:00:00Z',
  end: '2026-04-06T00:00:00Z',
};

export function fetcherOf(page: OccurrencePage | (() => Promise<OccurrencePage>)) {
  return vi.fn<OccurrenceFetcher>(async () => (typeof page === 'function' ? page() : page));
}
export const pageOf = (items: Occurrence[], truncated = false): OccurrencePage => ({
  items,
  truncated,
});

export const buttonNamed = (name: string) =>
  [...document.querySelectorAll('button')].find(
    (b) => b.textContent === name || b.getAttribute('aria-label') === name,
  ) as HTMLButtonElement;

/** Mounts `Calendar` over the fake grid (the test file mocks the real one) and reports a
 *  March range, as the grid's first `datesSet` would. */
export async function openCalendar(props: Partial<CalendarProps> = {}) {
  const { Calendar } = await import('../calendar/Calendar');
  const fetchOccurrences = (props.fetchOccurrences ?? fetcherOf(pageOf([]))) as ReturnType<
    typeof fetcherOf
  >;
  const view = await mount(
    <Calendar
      calendars={[calendarInfo()]}
      defaultTimezone="UTC"
      {...props}
      fetchOccurrences={fetchOccurrences}
    />,
  );
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush();
  return { view, fetchOccurrences };
}
