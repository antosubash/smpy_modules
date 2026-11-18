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
import { act, click } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/test-support/FakeGrid'));

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

const nameOf = (el: Element): string =>
  (el.getAttribute('aria-label') ?? el.textContent ?? '').trim();

const editing = {
  canCreate: true,
  onCreate: vi.fn(),
  onChange: vi.fn(async () => true),
  onMove: vi.fn(),
  pendingKeys: new Set<string>(),
};

it('every toolbar and filter control has an accessible name', async () => {
  const { view } = await open({
    calendars: [calendarInfo(), calendarInfo({ id: 'c2', name: 'Studio' })],
    categories: [{ id: 'k1', label: 'Talks' }],
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  const controls = [...document.querySelectorAll('button, input, [role=radio]')];
  expect(controls.length).toBeGreaterThan(8);
  for (const control of controls) {
    const labelled = control.closest('label')?.textContent?.trim();
    expect(nameOf(control) || labelled, control.outerHTML).toBeTruthy();
  }
  await view.unmount();
});

it('the view switcher is a pressed-state group of plain buttons', async () => {
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([])) });
  const group = buttonNamed('Month').closest('fieldset');
  const buttons = [...(group?.querySelectorAll('button') ?? [])];
  expect(buttons.map((b) => b.textContent)).toEqual(['Month', 'Week', 'Day', 'List']);
  expect(buttons.map((b) => b.getAttribute('aria-pressed'))).toEqual([
    'true',
    'false',
    'false',
    'false',
  ]);
  expect(buttons.every((b) => b.tabIndex >= 0 && b.type === 'button')).toBe(true);
  await click(buttonNamed('Week'));
  expect(fakeGrid.last?.view).toBe('week');
  expect(buttonNamed('Week').getAttribute('aria-pressed')).toBe('true');
  await view.unmount();
});

it('the grid region is labelled with the title and the wrapper is busy while loading', async () => {
  let release: (v: ReturnType<typeof pageOf>) => void = () => {};
  const pending = new Promise<ReturnType<typeof pageOf>>((resolve) => {
    release = resolve;
  });
  const { view } = await open({ fetchOccurrences: fetcherOf(() => pending) });
  expect(fakeGrid.last?.ariaLabel).toBe('March 2026');
  expect(document.querySelector('[aria-busy=true]')).toBeTruthy();
  await act(async () => release(pageOf([])));
  expect(document.querySelector('[aria-busy=true]')).toBeNull();
  await view.unmount();
});

it('the title is a polite live region', async () => {
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([])) });
  const title = document.querySelector('[data-testid=calendar-title]');
  expect(title?.tagName).toBe('H2');
  expect(title?.getAttribute('aria-live')).toBe('polite');
  expect(title?.textContent).toBe('March 2026');
  await view.unmount();
});

it('a draft, a cancelled and a read-only occurrence say so in words', async () => {
  const items = [
    occurrence({ key: 'd:0', title: 'Draft one', event_status: 'draft' }),
    occurrence({ key: 'x:0', title: 'Gone', status: 'cancelled' }),
    occurrence({ key: 'r:0', title: 'Locked', editable: false }),
  ];
  const { view } = await open({ editing, fetchOccurrences: fetcherOf(pageOf(items)) });
  const chip = (key: string) => document.querySelector(`[data-key="${key}"]`)?.textContent ?? '';
  expect(chip('d:0')).toContain('Draft');
  expect(chip('x:0')).toContain('Cancelled');
  const lock = document.querySelector('[data-key="r:0"] [role=img]');
  expect(lock?.getAttribute('aria-label')).toMatch(/^.+: .+/);
  await view.unmount();
});

it('Escape closes the popover and the event element is focused again', async () => {
  const element = document.createElement('button');
  document.body.appendChild(element);
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  await act(async () => fakeGrid.open('e1:0', element));
  expect(document.querySelector('[data-testid=calendar-detail]')).toBeTruthy();
  await act(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 30));
  expect(document.querySelector('[data-testid=calendar-detail]')).toBeNull();
  expect(document.activeElement).toBe(element);
  await view.unmount();
});

it('the popover actions are plain buttons and links in the tab order', async () => {
  const { view } = await open({ editing, fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const detail = document.querySelector('[role=dialog]');
  const actions = [...(detail?.querySelectorAll('a, button') ?? [])];
  expect(actions.map(nameOf)).toEqual(expect.arrayContaining(['Move…']));
  expect(actions.every((a) => (a as HTMLElement).tabIndex >= 0)).toBe(true);
  await view.unmount();
});

it('a timed block in week view stacks time and title so a narrow column keeps the title', async () => {
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([occurrence()])) });
  const chip = () => document.querySelector('[data-key="e1:0"] > span');
  expect(chip()?.className).not.toContain('flex-col');
  await click(buttonNamed('Week'));
  expect(chip()?.className).toContain('flex-col');
  expect(chip()?.textContent).toContain('Planning');
  await view.unmount();
});

it('a short block in week view keeps one line', async () => {
  const short = occurrence({ end: '2026-03-23T09:15:00Z' });
  const { view } = await open({ fetchOccurrences: fetcherOf(pageOf([short])) });
  await click(buttonNamed('Week'));
  expect(document.querySelector('[data-key="e1:0"] > span')?.className).not.toContain('flex-col');
  await view.unmount();
});
