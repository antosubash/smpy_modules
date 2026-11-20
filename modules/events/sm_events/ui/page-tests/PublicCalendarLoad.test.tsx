// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import { loadEventExtensions, resetLoader } from '../extensions/load';
import { clearExtensions, registerEventType } from '../extensions/registry';
import { buttonNamed, calendarInfo, MARCH } from './calendar-support';
import { flush, stubFetch } from './support';
import { act, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));
const { PublicCalendarGrid } = await import('../public/PublicCalendarGrid');

beforeEach(() => {
  fakeGrid.reset();
  clearExtensions();
  resetLoader();
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  clearExtensions();
  resetLoader();
});

function grid() {
  return (
    <PublicCalendarGrid
      apiUrl="/api/events/public/occurrences"
      calendars={[{ ...calendarInfo(), description: null, url: '', feed_url: '', slug: 'team' }]}
      categories={[]}
      defaultTimezone="UTC"
      initial={{ view: 'month', date: '2026-03-10' }}
    />
  );
}

it('a plugin load that finishes after the visitor moved on does not reset the calendar', async () => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  // The lazy extension chunk is still downloading when the calendar mounts.
  void loadEventExtensions({
    'records/events-extensions.ts': async () => {
      await gate;
      registerEventType({ id: 'acme:talk' });
    },
  });
  stubFetch({ 'GET /api/events/public/occurrences': { items: [], truncated: false } });
  const view = await mount(grid());
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await act(async () => buttonNamed('Next')?.click());
  expect(fakeGrid.handle.next).toHaveBeenCalled();
  const APRIL = { start: '2026-03-30T00:00:00Z', end: '2026-05-11T00:00:00Z' };
  // FullCalendar answers the navigation with the new range, as `datesSet` does.
  await act(async () => fakeGrid.emitRange(APRIL, 'April 2026', 'month', '2026-04-10'));
  const moved = fakeGrid.last?.date;
  expect(moved).toBe('2026-04-10');
  const mounts = fakeGrid.mounts;

  release(); // the chunk finishes: the registry is now loaded
  await flush();

  expect(fakeGrid.last?.date).toBe(moved); // still the month the visitor navigated to
  expect(fakeGrid.last?.view).toBe('month');
  expect(fakeGrid.mounts).toBe(mounts); // the grid was not mounted again
  await view.unmount();
});
