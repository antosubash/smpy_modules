// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/test-support/FakeGrid';
import { buttonNamed, MARCH } from './calendar-support';
import { category, flush, stubFetch } from './support';
import { act, click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'));
const { default: CalendarPage } = await import('../../pages/Calendar');

const calendars = [
  {
    id: 'c1',
    name: 'Team',
    color: '#2563eb',
    visibility: 'internal' as const,
    default_timezone: 'Europe/Vienna',
    can_write_events: true,
  },
  {
    id: 'c2',
    name: 'Board',
    color: '#16a34a',
    visibility: 'private' as const,
    default_timezone: 'UTC',
    can_write_events: false,
  },
];
const props = {
  calendars,
  categories: [category],
  default_timezone: 'Europe/Vienna',
  content_locales: ['en', 'de'],
  editor_url: '/admin/events/edit',
};
const OCCURRENCES = '/api/events/occurrences';

beforeEach(() => {
  fakeGrid.reset();
  history.replaceState(null, '', '/admin/events/');
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

async function open() {
  const calls = stubFetch({ [`GET ${OCCURRENCES}`]: { items: [], truncated: false } });
  const view = await mount(<CalendarPage {...props} />);
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush();
  return { view, calls };
}

it('reads the view, date and zone mode from the URL on load', async () => {
  history.replaceState(null, '', '/admin/events/?view=week&date=2026-03-30&tz=mine');
  const { view } = await open();
  expect(fakeGrid.last?.view).toBe('week');
  expect(fakeGrid.last?.date).toBe('2026-03-30');
  expect(fakeGrid.last?.timeZone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  await view.unmount();
});

it('ignores calendars in the URL that the viewer does not have', async () => {
  history.replaceState(null, '', '/admin/events/?calendar=ghost');
  const { view, calls } = await open();
  expect(calls[0]?.url).not.toContain('calendar=');
  await view.unmount();
});

it('writes the state with replaceState, never pushState', async () => {
  const replace = vi.spyOn(history, 'replaceState');
  const push = vi.spyOn(history, 'pushState');
  const { view } = await open();
  await click(buttonNamed('Day'));
  expect(location.search).toContain('view=day');
  expect(location.pathname).toBe('/admin/events/');
  expect(replace).toHaveBeenCalled();
  expect(push).not.toHaveBeenCalled();
  await view.unmount();
});

it('asks for titles in the console language', async () => {
  updateI18n({ locale: 'de', messages: {} });
  const { view, calls } = await open();
  expect(calls[0]?.url).toContain('locale=de');
  expect(calls[0]?.url).toContain('start=');
  await view.unmount();
});

it('falls back to the first content language when the console language is not one', async () => {
  updateI18n({ locale: 'fr', messages: {} });
  const { view, calls } = await open();
  expect(calls[0]?.url).toContain('locale=en');
  await view.unmount();
});

it('sends the server-side filters under the API names', async () => {
  history.replaceState(null, '', `/admin/events/?calendar=c1&category=${category.id}&type=event`);
  const { view, calls } = await open();
  const url = new URL(calls[0]?.url ?? '', 'http://localhost');
  expect(url.searchParams.getAll('calendar')).toEqual(['c1']);
  expect(url.searchParams.getAll('category')).toEqual([category.id]);
  expect(url.searchParams.getAll('type')).toEqual(['event']);
  await view.unmount();
});
