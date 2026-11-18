/** Shared by the calendar write tests: a harness around `useCalendarWrites` and the fixtures
 *  of a one-off and a weekly series. The test file mocks `sonner` itself. */
import { afterEach, beforeEach, vi } from 'vitest';
import { useCalendarWrites } from '../calendar/console/useCalendarWrites';
import type { OccurrenceChange } from '../calendar/types';
import { occurrence } from './calendar-support';
import { eventDetail } from './support';
import { act, mount } from './test-dom';

export const EVENT = '/api/events/events/e1';
export const PREVIEW = '/api/events/recurrence/preview';
export const EDITOR = '/admin/events/edit';

type Writes = ReturnType<typeof useCalendarWrites>;
export const api = { current: null as Writes | null };
export const invalidate = vi.fn();
export function Harness() {
  const writes = useCalendarWrites({ invalidate, editorUrl: EDITOR });
  api.current = writes;
  return <>{writes.dialogs}</>;
}

export const oneOff = () =>
  eventDetail({
    id: 'e1',
    revision: 7,
    starts_at: '2026-03-23T09:00:00Z',
    ends_at: '2026-03-23T10:00:00Z',
    start_local: '2026-03-23T10:00',
    end_local: '2026-03-23T11:00',
  });
export const weekly = (extra = {}) =>
  eventDetail({
    id: 'e1',
    revision: 7,
    rrule: 'FREQ=WEEKLY;BYDAY=MO',
    starts_at: '2026-03-02T09:00:00Z',
    ends_at: '2026-03-02T10:00:00Z',
    start_local: '2026-03-02T10:00',
    end_local: '2026-03-02T11:00',
    ...extra,
  });
export const instance = () => occurrence({ original_start: '2026-03-23T09:00:00Z' });
export const move = (o = occurrence()): OccurrenceChange => ({
  occurrence: o,
  kind: 'move',
  start: '2026-03-30T09:00:00Z',
  end: '2026-03-30T10:00:00Z',
  allDay: false,
});

export const start = (change: OccurrenceChange) => {
  const done = api.current?.onChange(change) ?? Promise.resolve(false);
  return done;
};
export const finish = async (done: Promise<boolean>) => {
  let result = false;
  await act(async () => {
    result = await done;
  });
  return result;
};

/** The mounted harness; `installHarness` mounts it for each test. */
export const mounted = { view: null as Awaited<ReturnType<typeof mount>> | null };
export function installHarness() {
  beforeEach(async () => {
    vi.clearAllMocks();
    mounted.view = await mount(<Harness />);
  });
  afterEach(async () => {
    await mounted.view?.unmount();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });
}
export const methods = (calls: { method: string }[]) => calls.map((c) => c.method);
