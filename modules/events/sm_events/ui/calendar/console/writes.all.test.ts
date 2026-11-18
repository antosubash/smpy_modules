import { describe, expect, it } from 'vitest';
import { planChange } from './writes';
import { allDayOccurrence, change, event, instance, series, VIENNA } from './writes-fixtures';

const SAO_PAULO = 'America/Sao_Paulo';

/** Weekly Wednesday 10:00-11:00 Vienna from 2026-03-04; the 2026-04-08 instance (CEST) was
 *  overridden to 14:00-15:00 (12:00Z-13:00Z). */
const wed = () =>
  series({
    rrule: 'FREQ=WEEKLY;BYDAY=WE',
    starts_at: '2026-03-04T09:00:00Z',
    ends_at: '2026-03-04T10:00:00Z',
    start_local: '2026-03-04T10:00',
    end_local: '2026-03-04T11:00',
  });
const moved = () =>
  instance({
    original_start: '2026-04-08T08:00:00Z',
    start: '2026-04-08T12:00:00Z',
    end: '2026-04-08T13:00:00Z',
  });
const unmoved = () =>
  instance({
    original_start: '2026-04-08T08:00:00Z',
    start: '2026-04-08T08:00:00Z',
    end: '2026-04-08T09:00:00Z',
  });

const timesOf = (plan: ReturnType<typeof planChange>) =>
  plan.kind === 'patch' ? plan.body.times : plan;
const timed = (start: string, end: string) => ({
  all_day: false,
  timezone: VIENNA,
  start,
  end,
});

describe('"all" on a timed instance', () => {
  it.each([
    {
      name: 'resize of an overridden instance changes only the master end (K1)',
      o: moved(),
      kind: 'resize' as const,
      to: ['2026-04-08T12:00:00Z', '2026-04-08T14:00:00Z'],
      want: timed('2026-03-04T10:00', '2026-03-04T12:00'),
    },
    {
      name: 'move of an overridden instance shifts by the drag, not by the override (K3)',
      o: moved(),
      kind: 'move' as const,
      to: ['2026-04-08T13:00:00Z', '2026-04-08T14:00:00Z'],
      want: timed('2026-03-04T11:00', '2026-03-04T12:00'),
    },
    {
      name: 'reschedule of an overridden instance shifts each edge by what changed',
      o: moved(),
      kind: 'reschedule' as const,
      to: ['2026-04-08T12:30:00Z', '2026-04-08T14:00:00Z'],
      want: timed('2026-03-04T10:30', '2026-03-04T12:00'),
    },
    {
      name: 'move of an unmoved instance',
      o: unmoved(),
      kind: 'move' as const,
      to: ['2026-04-09T08:00:00Z', '2026-04-09T09:00:00Z'],
      want: timed('2026-03-05T10:00', '2026-03-05T11:00'),
    },
    {
      name: 'resize of an unmoved instance',
      o: unmoved(),
      kind: 'resize' as const,
      to: ['2026-04-08T08:00:00Z', '2026-04-08T09:30:00Z'],
      want: timed('2026-03-04T10:00', '2026-03-04T11:30'),
    },
    {
      name: 'reschedule of an unmoved instance',
      o: unmoved(),
      kind: 'reschedule' as const,
      to: ['2026-04-08T09:00:00Z', '2026-04-08T11:00:00Z'],
      want: timed('2026-03-04T11:00', '2026-03-04T13:00'),
    },
  ])('$name', ({ o, kind, to, want }) => {
    expect(timesOf(planChange(change(o, kind, to[0], to[1]), wed(), 'all'))).toEqual(want);
  });

  it('refuses a master start shifted into the spring gap, without throwing (K6)', () => {
    const master = series({ start_local: '2026-03-01T02:30', end_local: '2026-03-01T03:30' });
    const o = instance({
      original_start: '2026-03-22T01:30:00Z',
      start: '2026-03-22T01:30:00Z',
      end: '2026-03-22T02:30:00Z',
    });
    const plan = planChange(
      change(o, 'move', '2026-04-19T00:30:00Z', '2026-04-19T01:30:00Z'),
      master,
      'all',
    );
    expect(plan).toEqual({ kind: 'refuse', code: 'invalid_local_time' });
  });

  it('refuses a drop on the second pass of the repeated hour with the ruled code (K6)', () => {
    const master = series({ start_local: '2026-10-18T02:30', end_local: '2026-10-18T03:30' });
    const o = instance({
      original_start: '2026-10-18T00:30:00Z',
      start: '2026-10-18T00:30:00Z',
      end: '2026-10-18T01:30:00Z',
    });
    // 2026-10-25T01:30Z is 02:30 the second time round in Vienna.
    const plan = planChange(
      change(o, 'move', '2026-10-25T01:30:00Z', '2026-10-25T02:30:00Z'),
      master,
      'all',
    );
    expect(plan).toEqual({ kind: 'refuse', code: 'repeated_local_time' });
  });
});

describe('"all" on an all-day instance', () => {
  const master = () =>
    event({
      all_day: true,
      timezone: SAO_PAULO,
      rrule: 'FREQ=WEEKLY',
      start_local: '2026-03-02',
      end_local: '2026-03-03',
    });
  // The 2026-03-16 instance was overridden to 03-17..03-18 (inclusive), shown 03-17..03-19.
  const movedDay = () =>
    allDayOccurrence({
      timezone: SAO_PAULO,
      original_start: '2026-03-16T03:00:00Z',
      start_date: '2026-03-17',
      end_date: '2026-03-19',
    });
  const plainDay = () =>
    allDayOccurrence({
      timezone: SAO_PAULO,
      original_start: '2026-03-16T03:00:00Z',
      start_date: '2026-03-16',
      end_date: '2026-03-18',
    });
  const allDay = (start: string, end: string) => ({
    all_day: true,
    timezone: SAO_PAULO,
    start,
    end,
  });

  it.each([
    {
      name: 'resize of an overridden instance (K2)',
      o: movedDay(),
      kind: 'resize' as const,
      to: ['2026-03-17', '2026-03-20'],
      want: allDay('2026-03-02', '2026-03-04'),
    },
    {
      name: 'move of an overridden instance by one day (K3)',
      o: movedDay(),
      kind: 'move' as const,
      to: ['2026-03-18', '2026-03-20'],
      want: allDay('2026-03-03', '2026-03-04'),
    },
    {
      name: 'reschedule of an overridden instance',
      o: movedDay(),
      kind: 'reschedule' as const,
      to: ['2026-03-16', '2026-03-20'],
      want: allDay('2026-03-01', '2026-03-04'),
    },
    {
      name: 'move of an unmoved instance',
      o: plainDay(),
      kind: 'move' as const,
      to: ['2026-03-18', '2026-03-20'],
      want: allDay('2026-03-04', '2026-03-05'),
    },
    {
      name: 'resize of an unmoved instance',
      o: plainDay(),
      kind: 'resize' as const,
      to: ['2026-03-16', '2026-03-19'],
      want: allDay('2026-03-02', '2026-03-04'),
    },
  ])('$name', ({ o, kind, to, want }) => {
    expect(timesOf(planChange(change(o, kind, to[0], to[1], true), master(), 'all'))).toEqual(want);
  });
});
