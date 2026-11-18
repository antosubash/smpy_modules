// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/test-support/FakeGrid';
import {
  buttonNamed,
  calendarInfo,
  fetcherOf,
  occurrence,
  openCalendar as open,
  pageOf,
} from './calendar-support';
import { flush } from './support';
import { act, click } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'));

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

const grid = (zone: string) => [calendarInfo({ default_timezone: zone })];

it('shows the grid time and, when it differs, the event own time', async () => {
  const { view } = await open({
    calendars: grid('America/New_York'),
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const detail = document.querySelector('[data-testid=calendar-detail]');
  expect(detail?.textContent).toContain('5:00');
  expect(detail?.textContent).toContain('Event time in Europe/Vienna');
  expect(detail?.textContent).toContain('10:00');
  await view.unmount();
});

it('shows only one time when the grid is the event zone', async () => {
  const { view } = await open({
    calendars: grid('Europe/Vienna'),
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const detail = document.querySelector('[data-testid=calendar-detail]');
  expect(detail?.textContent).toContain('10:00');
  expect(detail?.textContent).not.toContain('Event time in');
  await view.unmount();
});

it('shows an all-day occurrence as dates only', async () => {
  const allDay = occurrence({
    all_day: true,
    start_date: '2026-03-29',
    end_date: '2026-03-30',
  });
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([allDay])) });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const detail = document.querySelector('[data-testid=calendar-detail]');
  expect(detail?.textContent).toContain('Mar 29, 2026');
  expect(detail?.textContent).not.toMatch(/\d:\d\d/);
  await view.unmount();
});

const editing = {
  canCreate: true,
  onCreate: vi.fn(),
  onChange: vi.fn(async () => true),
  onMove: vi.fn(),
  pendingKeys: new Set<string>(),
};

it('says why a published occurrence is read-only on a writable calendar', async () => {
  const published = occurrence({ editable: false, event_status: 'published' });
  const { view } = await open({ editing, fetchOccurrences: fetcherOf(pageOf([published])) });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const text = document.querySelector('[data-testid=calendar-detail]')?.textContent;
  expect(text).toContain('Published: only a publisher can change it');
  expect(document.body.textContent).not.toContain('Move…');
  await view.unmount();
});

it('says a view-only calendar is view only', async () => {
  const locked = occurrence({ editable: false });
  const { view } = await open({
    editing,
    calendars: [calendarInfo({ can_write_events: false })],
    fetchOccurrences: fetcherOf(pageOf([locked])),
  });
  await act(async () => fakeGrid.open('e1:0', document.body));
  expect(document.querySelector('[data-testid=calendar-detail]')?.textContent).toContain(
    'You can view this calendar only',
  );
  expect(document.body.textContent).not.toContain('Move…');
  await view.unmount();
});

it('offers Move… for an editable occurrence', async () => {
  const { view } = await open({ editing, fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  await act(async () => fakeGrid.open('e1:0', document.body));
  await click(buttonNamed('Move…'));
  expect(editing.onMove).toHaveBeenCalledWith(expect.objectContaining({ key: 'e1:0' }));
  await view.unmount();
});

it('badges a title that fell back to another language', async () => {
  updateI18n({ locale: 'de', messages: {} });
  const { view } = await open({
    fetchOccurrences: fetcherOf(pageOf([occurrence({ lang: 'en' })])),
  });
  await act(async () => fakeGrid.open('e1:0', document.body));
  expect(document.querySelector('[data-testid=calendar-detail] .uppercase')?.textContent).toContain(
    'en',
  );
  await view.unmount();
});

it('has no create and no move without an editing prop', async () => {
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  expect(fakeGrid.last?.editing).toBeUndefined();
  await act(async () => fakeGrid.open('e1:0', document.body));
  expect(document.body.textContent).not.toContain('Move…');
  await view.unmount();
});

it('closing the popover returns focus to the event element', async () => {
  const element = document.createElement('button');
  document.body.appendChild(element);
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  await act(async () => fakeGrid.open('e1:0', element));
  await act(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });
  await flush(30);
  expect(document.activeElement).toBe(element);
  await view.unmount();
});
