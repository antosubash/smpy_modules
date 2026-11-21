// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toEventInput } from '../calendar/adapter/mapping';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import type { OccurrenceChange } from '../calendar/types';
import { MARCH, occurrence } from './calendar-support';
import { eventDetail, flush, refusal, stubFetch } from './support';
import { act, mount } from './test-dom';

vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));
const { ConsoleCalendar } = await import('../calendar/console/ConsoleCalendar');

const OCCURRENCES = '/api/events/occurrences';
const EVENT = '/api/events/events/e1';
const calendars = [
  {
    id: 'c1',
    name: 'Team',
    color: '#2563eb',
    visibility: 'internal' as const,
    default_timezone: 'Europe/Vienna',
    can_write_events: true,
  },
];
const stored = () =>
  eventDetail({
    id: 'e1',
    revision: 7,
    starts_at: '2026-03-23T09:00:00Z',
    ends_at: '2026-03-23T10:00:00Z',
    start_local: '2026-03-23T10:00',
    end_local: '2026-03-23T11:00',
  });
const drop = (o = occurrence()): OccurrenceChange => ({
  occurrence: o,
  kind: 'move',
  start: '2026-03-30T09:00:00Z',
  end: '2026-03-30T10:00:00Z',
  allDay: false,
});

async function open(items = [occurrence()], routes: Record<string, unknown> = {}) {
  const calls = stubFetch({
    [`GET ${OCCURRENCES}`]: { items, truncated: false },
    [`GET ${EVENT}`]: stored(),
    ...routes,
  });
  const view = await mount(
    <ConsoleCalendar
      calendars={calendars}
      categories={[]}
      defaultTimezone="Europe/Vienna"
      contentLocales={['en']}
      editorUrl="/admin/events/edit"
    />,
  );
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush();
  return { view, calls };
}

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('a change from the grid', () => {
  it('reaches the write flow, resolves true and refetches the range', async () => {
    const { view, calls } = await open(undefined, { [`PATCH ${EVENT}`]: stored() });
    const before = calls.filter((c) => c.url.startsWith(OCCURRENCES)).length;
    let kept: boolean | undefined;
    await act(async () => {
      kept = await fakeGrid.change(drop());
    });
    await flush();
    expect(kept).toBe(true);
    expect(calls.some((c) => c.method === 'PATCH')).toBe(true);
    expect(calls.filter((c) => c.url.startsWith(OCCURRENCES)).length).toBe(before + 1);
    await view.unmount();
  });

  it('resolves false when the server refuses, so the grid reverts', async () => {
    const { view } = await open(undefined, { [`PATCH ${EVENT}`]: refusal(409, 'stale') });
    let kept: boolean | undefined;
    await act(async () => {
      kept = await fakeGrid.change(drop());
    });
    expect(kept).toBe(false);
    await view.unmount();
  });

  it('keeps the occurrence out of reach while its write runs', async () => {
    let release: (value: unknown) => void = () => {};
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const { view } = await open(undefined, {
      [`GET ${EVENT}`]: async () => {
        await gate;
        return stored();
      },
      [`PATCH ${EVENT}`]: stored(),
    });
    let done: Promise<boolean> | undefined;
    await act(async () => {
      done = fakeGrid.change(drop());
    });
    const grid = fakeGrid.last;
    const item = grid?.items[0];
    expect(item && toEventInput(item, grid?.editing)).toMatchObject({
      startEditable: false,
      durationEditable: false,
    });
    expect(document.querySelector('[data-key="e1:0"] [aria-busy="true"]')).not.toBeNull();
    release(null);
    await act(async () => {
      await done;
    });
    await flush();
    const after = fakeGrid.last;
    expect(toEventInput(after?.items[0] ?? occurrence(), after?.editing)).toMatchObject({
      startEditable: true,
    });
    await view.unmount();
  });

  it('is never editable for an occurrence the viewer may not change', async () => {
    const { view } = await open([occurrence({ editable: false })]);
    const grid = fakeGrid.last;
    expect(grid?.editing).toBeDefined();
    expect(toEventInput(grid?.items[0] ?? occurrence(), grid?.editing)).toMatchObject({
      startEditable: false,
      durationEditable: false,
    });
    await view.unmount();
  });
});
