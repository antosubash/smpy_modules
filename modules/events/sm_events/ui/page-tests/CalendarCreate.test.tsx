// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/test-support/FakeGrid';
import type { CalendarInfo } from '../calendar/types';
import { calendarInfo, MARCH } from './calendar-support';
import { eventDetail, field, flush, stubFetch, submit } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'));
const { ConsoleCalendar } = await import('../calendar/console/ConsoleCalendar');

const OCCURRENCES = '/api/events/occurrences';
const slot = { allDay: false, start: '2026-07-01T08:00:00Z', end: '2026-07-01T09:00:00Z' };
const TEAM = calendarInfo({ id: 'c1', name: 'Team' });
const BOARD = calendarInfo({ id: 'c2', name: 'Board', default_timezone: 'America/New_York' });

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function open(calendars: CalendarInfo[], initialState = {}) {
  const calls = stubFetch({
    [`GET ${OCCURRENCES}`]: { items: [], truncated: false },
    'POST /api/events/events': () => eventDetail({ id: 'new1' }),
  });
  const view = await mount(
    <ConsoleCalendar
      calendars={calendars}
      categories={[]}
      defaultTimezone="Europe/Vienna"
      contentLocales={['en']}
      editorUrl="/admin/events/edit"
      initialState={initialState}
    />,
  );
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush();
  return { view, calls };
}

it('a selection on the grid opens the quick-create dialog and creating refetches', async () => {
  const { view, calls } = await open([TEAM]);
  const fetches = () => calls.filter((c) => c.url.startsWith(OCCURRENCES)).length;
  const before = fetches();
  expect(fakeGrid.last?.editing?.canCreate).toBe(true);
  await act(async () => fakeGrid.select(slot));
  expect(fakeGrid.last?.editing?.creating).toBe(true);
  await setValue(field('quick-title'), 'Concert');
  await submit();
  await flush();
  expect(calls.some((c) => c.method === 'POST')).toBe(true);
  expect(fetches()).toBe(before + 1);
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(fakeGrid.last?.editing?.creating).toBe(false);
  await view.unmount();
});

it('cannot create when no calendar is writable', async () => {
  const { view } = await open([calendarInfo({ can_write_events: false })]);
  expect(fakeGrid.last?.editing?.canCreate).toBe(false);
  await view.unmount();
});

it('starts on the one calendar that is shown', async () => {
  const { view } = await open([TEAM, BOARD], { calendars: ['c2'] });
  await act(async () => fakeGrid.select(slot));
  expect((field('quick-calendar') as HTMLSelectElement).value).toBe('c2');
  expect(field('quick-start').value).toBe('2026-07-01T04:00');
  await view.unmount();
});

it('starts on the first writable calendar when several are shown', async () => {
  const { view } = await open([TEAM, BOARD]);
  await act(async () => fakeGrid.select(slot));
  expect((field('quick-calendar') as HTMLSelectElement).value).toBe('c1');
  await view.unmount();
});

it('offers no create when the only shown calendars are read-only (K7)', async () => {
  const readOnly = calendarInfo({ id: 'c3', name: 'Board', can_write_events: false });
  const { view } = await open([TEAM, readOnly], { calendars: ['c3'] });
  expect(fakeGrid.last?.editing?.canCreate).toBe(false);
  await view.unmount();
});

it('never starts a draft on a hidden calendar (K7)', async () => {
  const readOnly = calendarInfo({ id: 'c3', name: 'Board', can_write_events: false });
  const { view } = await open([TEAM, BOARD, readOnly], { calendars: ['c2', 'c3'] });
  expect(fakeGrid.last?.editing?.canCreate).toBe(true);
  await act(async () => fakeGrid.select(slot));
  const options = [...(field('quick-calendar') as HTMLSelectElement).options].map((o) => o.value);
  expect(options).toEqual(['c2']);
  await view.unmount();
});
