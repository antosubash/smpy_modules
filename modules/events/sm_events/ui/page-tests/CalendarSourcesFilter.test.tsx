// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import {
  calendarInfo,
  fetcherOf,
  MARCH,
  occurrence,
  openCalendar,
  pageOf,
} from './calendar-support';
import { act } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
});

const options = [
  { id: 'events', label: 'Events' },
  { id: 'records:dates', label: 'Deadlines' },
  { id: 'acme:talks', label: 'Talks' },
];

const box = (label: string) =>
  [...document.querySelectorAll('fieldset label')]
    .find((l) => l.textContent?.includes(label))
    ?.querySelector('input') as HTMLInputElement;
const checked = () => options.map((o) => box(o.label).checked);

async function toggle(label: string) {
  await act(async () => box(label).click());
  await act(async () => new Promise((r) => setTimeout(r, 10)));
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
}

const open = (props = {}) =>
  openCalendar({
    sources: options,
    calendars: [calendarInfo()],
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
    ...props,
  });
const lastSources = (f: ReturnType<typeof fetcherOf>) => f.mock.calls.at(-1)?.[0]?.sources;

it('shows every source checked while no filter is active, and asks for all of them', async () => {
  const { view, fetchOccurrences } = await open();
  expect(checked()).toEqual([true, true, true]);
  expect(lastSources(fetchOccurrences)).toEqual([]);
  await view.unmount();
});

it('unchecking one filters it out and leaves the others checked', async () => {
  const onStateChange = vi.fn();
  const { view, fetchOccurrences } = await open({ onStateChange });
  await toggle('Deadlines');
  expect(checked()).toEqual([true, false, true]);
  expect(lastSources(fetchOccurrences)).toEqual(['events', 'acme:talks']);
  expect(onStateChange.mock.lastCall?.[0].sources).toEqual(['events', 'acme:talks']);
  await view.unmount();
});

it('checking it back is no filter again: the state stays minimal', async () => {
  const onStateChange = vi.fn();
  const { view } = await open({ onStateChange });
  await toggle('Deadlines');
  await toggle('Deadlines');
  expect(checked()).toEqual([true, true, true]);
  expect(onStateChange.mock.lastCall?.[0].sources).toEqual([]);
  await view.unmount();
});

it('an old ?source= link keeps working: only the named source is checked', async () => {
  const { view, fetchOccurrences } = await open({ initialState: { sources: ['acme:talks'] } });
  expect(checked()).toEqual([false, false, true]);
  expect(lastSources(fetchOccurrences)).toEqual(['acme:talks']);
  await view.unmount();
});

it('unchecking the last one shows the same empty state as no calendar selected', async () => {
  const { view, fetchOccurrences } = await open({ initialState: { sources: ['acme:talks'] } });
  const calls = fetchOccurrences.mock.calls.length;
  await toggle('Talks');
  expect(checked()).toEqual([false, false, false]);
  expect(document.body.textContent).toContain('Select a calendar to see its events.');
  expect(fetchOccurrences.mock.calls.length).toBe(calls); // nothing is asked for
  await toggle('Talks');
  expect(checked()).toEqual([false, false, true]);
  await view.unmount();
});
