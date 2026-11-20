// @vitest-environment happy-dom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import { resetReminderStatus } from '../utils/api-reminders';
import { fetcherOf, occurrence, openCalendar as open, pageOf } from './calendar-support';
import { stubFetch } from './support';
import { act } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

const editing = {
  canCreate: true,
  onCreate: vi.fn(),
  onChange: vi.fn(async () => true),
  onMove: vi.fn(),
  pendingKeys: new Set<string>(),
};
const STATUS = '/api/events/reminders/status';
const FOLLOW = '/api/events/events/e1/follow';

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  vi.unstubAllGlobals();
  resetReminderStatus();
  document.body.innerHTML = '';
});

async function openDetail(over: Record<string, unknown>) {
  const calls = stubFetch({
    [`GET ${STATUS}`]: { available: true, leads: [15, 60, 1440, 10080] },
    [`GET ${FOLLOW}`]: { leads: [], defaults: [60], next_due: {}, deliverable: true, code: null },
  });
  const { view } = await open({
    editing,
    fetchOccurrences: fetcherOf(pageOf([occurrence(over)])),
  });
  await act(async () => fakeGrid.open('e1:0', document.body));
  await act(async () => undefined);
  return { calls, view };
}

it('offers "Remind me" on a published event of the events source', async () => {
  const { view } = await openDetail({ event_status: 'published' });
  expect(document.querySelector('[data-testid="remind-me"]')).not.toBeNull();
  await view.unmount();
});

it.each(['draft', 'in_review', 'scheduled'])('does not offer it on a %s event', async (status) => {
  const { calls, view } = await openDetail({ event_status: status });
  expect(document.querySelector('[data-testid="remind-me"]')).toBeNull();
  expect(calls.filter((c) => c.url.includes('/follow'))).toEqual([]);
  await view.unmount();
});

it('does not offer it on a date from another source', async () => {
  const { view } = await openDetail({ source: 'records:dates', event_id: null });
  expect(document.querySelector('[data-testid="remind-me"]')).toBeNull();
  await view.unmount();
});
