// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import {
  api,
  EVENT,
  finish,
  Harness,
  installHarness,
  instance,
  invalidate,
  methods,
  mounted,
  move,
  oneOff,
  start,
  weekly,
} from './calendar-writes-support';
import { button, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { toast } = await import('sonner');
installHarness();

describe('one-off', () => {
  it('sends one GET and one PATCH with the fetched revision', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: oneOff() });
    expect(await finish(start(move()))).toBe(true);
    expect(methods(calls)).toEqual(['GET', 'PATCH']);
    expect(calls[1]?.body).toEqual({
      expected_revision: 7,
      times: {
        all_day: false,
        timezone: 'Europe/Vienna',
        start: '2026-03-30T11:00',
        end: '2026-03-30T12:00',
      },
    });
    expect(toast.success).toHaveBeenCalledWith('Moved');
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('says "Resized" for a resize', async () => {
    stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: oneOff() });
    const change = { ...move(), kind: 'resize' as const, end: '2026-03-23T11:00:00Z' };
    expect(await finish(start(change))).toBe(true);
    expect(toast.success).toHaveBeenCalledWith('Resized');
  });
});

describe('series', () => {
  it('asks this one or all, and cancel sends nothing and reverts', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: weekly() });
    const done = start(move(instance()));
    await flush();
    expect(document.body.textContent).toContain('Only this occurrence');
    await click(button('Cancel'));
    expect(await finish(done)).toBe(false);
    expect(methods(calls)).toEqual(['GET']);
    expect(toast.error).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('"only this occurrence" posts an override', async () => {
    const calls = stubFetch({
      [`GET ${EVENT}`]: weekly(),
      [`POST ${EVENT}/overrides`]: { id: 1, event_revision: 8 },
    });
    const done = start(move(instance()));
    await flush();
    await click(button('Only this occurrence'));
    expect(await finish(done)).toBe(true);
    expect(calls[1]?.body).toEqual({
      expected_revision: 7,
      original_start: '2026-03-23T09:00:00Z',
      kind: 'moved',
      start: '2026-03-30T11:00',
      end: '2026-03-30T12:00',
    });
  });

  it('"all occurrences" patches the master', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: weekly(), [`PATCH ${EVENT}`]: weekly() });
    const done = start(move(instance()));
    await flush();
    await click(button('All occurrences'));
    expect(await finish(done)).toBe(true);
    expect(calls[1]?.body).toMatchObject({
      times: { start: '2026-03-09T11:00', end: '2026-03-09T12:00' },
    });
    expect(JSON.stringify(calls[1]?.body)).not.toContain('rrule');
  });
});

describe('lifetime', () => {
  it('marks the occurrence pending during the write and clears it after', async () => {
    let release: (value: unknown) => void = () => {};
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    stubFetch({
      [`GET ${EVENT}`]: async () => {
        await gate;
        return oneOff();
      },
      [`PATCH ${EVENT}`]: oneOff(),
    });
    const done = start(move());
    await flush();
    expect(api.current?.pendingKeys.has('e1:0')).toBe(true);
    release(null);
    expect(await finish(done)).toBe(true);
    expect(api.current?.pendingKeys.has('e1:0')).toBe(false);
  });

  it('runs two writes on one event one after the other', async () => {
    const order: string[] = [];
    stubFetch({
      [`GET ${EVENT}`]: () => {
        order.push('GET');
        return oneOff();
      },
      [`PATCH ${EVENT}`]: async () => {
        order.push('PATCH start');
        await new Promise((resolve) => setTimeout(resolve, 20));
        order.push('PATCH end');
        return oneOff();
      },
    });
    const first = start(move());
    const second = start({ ...move(), start: '2026-03-31T09:00:00Z', end: '2026-03-31T10:00:00Z' });
    await finish(Promise.all([first, second]).then(() => true));
    // The second GET waits for the first PATCH to finish.
    expect(order).toEqual(['GET', 'PATCH start', 'PATCH end', 'GET', 'PATCH start', 'PATCH end']);
  });

  it('a completion after the calendar closed shows nothing and refreshes nothing', async () => {
    let release: (value: unknown) => void = () => {};
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    stubFetch({
      [`GET ${EVENT}`]: async () => {
        await gate;
        return oneOff();
      },
      [`PATCH ${EVENT}`]: oneOff(),
    });
    const done = start(move());
    await flush();
    await mounted.view?.unmount();
    release(null);
    await done;
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
    mounted.view = await mount(<Harness />);
  });
});
