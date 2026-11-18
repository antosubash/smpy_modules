// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/test-support/FakeGrid';
import type { CalendarProps } from '../calendar/types';
import { ApiError } from '../utils/api';
import {
  buttonNamed,
  calendarInfo,
  fetcherOf,
  occurrence,
  openCalendar,
  pageOf,
} from './calendar-support';
import { flush } from './support';
import { act, click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'));

const checkbox = (label: string) =>
  [...document.querySelectorAll('label')]
    .find((l) => l.textContent?.includes(label))
    ?.querySelector('input') as HTMLInputElement;

const open = openCalendar;

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

it('drives the grid from the toolbar, and names every button', async () => {
  const { view } = await open();
  await click(buttonNamed('Today'));
  await click(buttonNamed('Previous'));
  await click(buttonNamed('Next'));
  expect(fakeGrid.handle.today).toHaveBeenCalledTimes(1);
  expect(fakeGrid.handle.prev).toHaveBeenCalledTimes(1);
  expect(fakeGrid.handle.next).toHaveBeenCalledTimes(1);
  await view.unmount();
});

it('switches the view, marks it pressed and reports the state', async () => {
  const onStateChange = vi.fn();
  const { view } = await open({ onStateChange });
  await click(buttonNamed('Week'));
  expect(fakeGrid.last?.view).toBe('week');
  expect(buttonNamed('Week').getAttribute('aria-pressed')).toBe('true');
  expect(buttonNamed('Month').getAttribute('aria-pressed')).toBe('false');
  expect(onStateChange).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'week' }));
  await view.unmount();
});

it('takes the title from the grid', async () => {
  const { view } = await open();
  expect(document.querySelector('[data-testid=calendar-title]')?.textContent).toBe('March 2026');
  await view.unmount();
});

it('asks the server for the calendars that are still checked', async () => {
  const calendars = [calendarInfo(), calendarInfo({ id: 'c2', name: 'Board' })];
  const { view, fetchOccurrences } = await open({ calendars });
  expect(fetchOccurrences).toHaveBeenCalledTimes(1);
  expect(fetchOccurrences.mock.calls[0]?.[0].calendars).toEqual([]);
  await click(checkbox('Team'));
  await flush();
  expect(fetchOccurrences).toHaveBeenCalledTimes(2);
  expect(fetchOccurrences.mock.calls[1]?.[0].calendars).toEqual(['c2']);
  await view.unmount();
});

it('fetches nothing and says so when no calendar is checked', async () => {
  const { view, fetchOccurrences } = await open();
  fetchOccurrences.mockClear();
  await click(checkbox('Team'));
  await flush();
  expect(fetchOccurrences).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain('Select a calendar to see its events.');
  await view.unmount();
});

it('names each calendar visibility in words', async () => {
  const calendars = [
    calendarInfo({ visibility: 'private' }),
    calendarInfo({ id: 'c2', name: 'Board', visibility: 'internal' }),
    calendarInfo({ id: 'c3', name: 'Site', visibility: 'public' }),
  ];
  const { view } = await open({ calendars });
  expect(checkbox('Team').closest('label')?.textContent).toContain('Private');
  expect(checkbox('Board').closest('label')?.textContent).toContain('Internal');
  expect(checkbox('Site').closest('label')?.textContent).toContain('Public');
  await view.unmount();
});

it('shows the type filter only with two types', async () => {
  const one = await open({ types: [{ id: 'event', label: 'Events' }] });
  expect(document.body.textContent).not.toContain('Types');
  await one.view.unmount();
  const two = await open({
    types: [
      { id: 'event', label: 'Events' },
      { id: 'holiday', label: 'Holidays' },
    ],
  });
  expect(document.body.textContent).toContain('Types');
  await two.view.unmount();
});

it('says loading while a request is open', async () => {
  const fetchOccurrences = fetcherOf(() => new Promise(() => {}));
  const { view } = await open({ fetchOccurrences });
  const status = document.querySelector('[role=status]');
  expect(status?.textContent).toContain('Loading');
  await view.unmount();
});

it('shows an error in an alert, and Retry fetches again', async () => {
  let fail = true;
  const fetchOccurrences = fetcherOf(async () => {
    if (fail) throw new ApiError(500, 'boom');
    return pageOf([]);
  });
  const { view } = await open({ fetchOccurrences });
  expect(document.querySelector('[role=alert]')?.textContent).toContain('Retry');
  fail = false;
  await click(buttonNamed('Retry'));
  await flush();
  expect(fetchOccurrences).toHaveBeenCalledTimes(2);
  expect(document.querySelector('[role=alert]')).toBeNull();
  await view.unmount();
});

it('says when the range is empty', async () => {
  const { view } = await open();
  expect(document.body.textContent).toContain('Nothing in this range');
  await view.unmount();
});

it('keeps a notice when the page was truncated', async () => {
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([occurrence()], true)) });
  expect(document.querySelector('[role=note]')?.textContent).toContain('first 2,000 items');
  await view.unmount();
});

it('writes draft, in review and cancelled in words in the chip', async () => {
  const items = [
    occurrence({ key: 'a', event_status: 'draft' }),
    occurrence({ key: 'b', event_status: 'in_review' }),
    occurrence({ key: 'c', status: 'cancelled' }),
  ];
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf(items)) });
  const chip = (key: string) => document.querySelector(`[data-key=${key}]`)?.textContent;
  expect(chip('a')).toContain('Draft');
  expect(chip('b')).toContain('In review');
  expect(chip('c')).toContain('Cancelled');
  await view.unmount();
});

it('shows the title as text, never as markup', async () => {
  const hostile = occurrence({ title: '<img src=x onerror=alert(1)>' });
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([hostile])) });
  expect(document.querySelector('[data-key] img')).toBeNull();
  expect(document.querySelector('[data-key] bdi')?.textContent).toBe(hostile.title);
  await view.unmount();
});
