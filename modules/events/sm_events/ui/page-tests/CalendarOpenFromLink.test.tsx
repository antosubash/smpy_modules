// @vitest-environment happy-dom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import { fetcherOf, occurrence, openCalendar, pageOf } from './calendar-support';
import { act } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
});

const open = async (props: Parameters<typeof openCalendar>[0]) => {
  const opened = await openCalendar(props);
  await act(async () => new Promise((r) => setTimeout(r, 40))); // the frame the open waits for
  return opened;
};
const detail = () => document.querySelector('[data-testid=calendar-detail]');

it('opens the detail of the occurrence a mail link names, read-only', async () => {
  const { view } = await open({
    initialOpen: 'e1:0',
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  expect(detail()?.textContent).toContain('Planning');
  expect(document.body.textContent).not.toContain('Move…'); // no editing rights were asked for
  await view.unmount();
});

it('opens nothing for a key that is not on the page, and does not mind', async () => {
  const { view } = await open({
    initialOpen: 'gone:9',
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  expect(detail()).toBeNull();
  await view.unmount();
});

it('opens it once: closing it does not bring it back', async () => {
  const { view } = await open({
    initialOpen: 'e1:0',
    fetchOccurrences: fetcherOf(pageOf([occurrence()])),
  });
  expect(detail()).not.toBeNull();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  expect(detail()).toBeNull();
  await view.unmount();
});
