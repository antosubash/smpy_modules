import { describe, expect, it } from 'vitest';
import { isStale, planChange } from './writes';
import {
  allDayEvent,
  allDayOccurrence,
  change,
  event,
  instance,
  occurrence,
  series,
  VIENNA,
} from './writes-fixtures';

describe('series instance', () => {
  it('"this one" is a moved override on the original start, in Vienna wall clock', () => {
    const plan = planChange(
      change(instance(), 'move', '2026-03-30T09:00:00Z', '2026-03-30T10:00:00Z'),
      series(),
      'one',
    );
    expect(plan).toEqual({
      kind: 'override',
      eventId: 'e1',
      body: {
        expected_revision: 7,
        original_start: '2026-03-23T09:00:00Z',
        kind: 'moved',
        start: '2026-03-30T11:00',
        end: '2026-03-30T12:00',
      },
    });
  });

  it('"this one" on an all-day instance sends dates with an inclusive end', () => {
    const o = allDayOccurrence({ original_start: '2026-07-31T22:00:00Z' });
    const plan = planChange(
      change(o, 'move', '2026-08-03', '2026-08-06', true),
      allDayEvent({ rrule: 'FREQ=WEEKLY' }),
      'one',
    );
    expect(plan).toMatchObject({
      kind: 'override',
      body: { original_start: '2026-07-31T22:00:00Z', start: '2026-08-03', end: '2026-08-05' },
    });
  });

  it('"all" shifts the master by the wall-clock difference in the event zone', () => {
    const plan = planChange(
      change(instance(), 'move', '2026-03-30T09:00:00Z', '2026-03-30T10:00:00Z'),
      series(),
      'all',
    );
    expect(plan).toEqual({
      kind: 'patch',
      eventId: 'e1',
      body: {
        expected_revision: 7,
        times: {
          all_day: false,
          timezone: VIENNA,
          start: '2026-03-09T11:00',
          end: '2026-03-09T12:00',
        },
      },
    });
  });

  it('"all" never rewrites the rule', () => {
    const plan = planChange(
      change(instance(), 'move', '2026-03-23T10:00:00Z', '2026-03-23T11:00:00Z'),
      series(),
      'all',
    );
    expect(plan).toMatchObject({ kind: 'patch' });
    expect(JSON.stringify(plan)).not.toContain('rrule');
  });

  it('"all" resize sets the master duration to the instance\'s new duration', () => {
    const plan = planChange(
      change(instance(), 'resize', '2026-03-23T09:00:00Z', '2026-03-23T11:30:00Z'),
      series(),
      'all',
    );
    expect(plan).toMatchObject({
      body: { times: { start: '2026-03-02T10:00', end: '2026-03-02T12:30' } },
    });
  });

  it('"all" all-day shifts dates and keeps the length', () => {
    const o = allDayOccurrence({
      original_start: '2026-08-07T22:00:00Z',
      start_date: '2026-08-08',
      end_date: '2026-08-11',
    });
    const ev = allDayEvent({ rrule: 'FREQ=WEEKLY' });
    const plan = planChange(change(o, 'move', '2026-08-10', '2026-08-13', true), ev, 'all');
    // The 8 August instance moves two days, so the master (1 to 3 August) moves two days.
    expect(plan).toMatchObject({
      body: { times: { all_day: true, start: '2026-08-03', end: '2026-08-05' } },
    });
  });

  it('"all" onto a nonexistent master time is refused', () => {
    const master = series({
      start_local: '2026-03-01T02:30',
      end_local: '2026-03-01T03:30',
      starts_at: '2026-03-01T01:30:00Z',
      ends_at: '2026-03-01T02:30:00Z',
    });
    const o = instance({
      original_start: '2026-03-22T01:30:00Z',
      start: '2026-03-22T01:30:00Z',
      end: '2026-03-22T02:30:00Z',
    });
    // Move the whole series by 28 days at the same time: master lands 2026-03-29T02:30.
    const plan = planChange(
      change(o, 'move', '2026-04-19T00:30:00Z', '2026-04-19T01:30:00Z'),
      master,
      'all',
    );
    expect(plan).toMatchObject({ kind: 'refuse' });
  });

  it('a resize to the repeated hour on "all" is refused', () => {
    const master = series({
      start_local: '2026-10-25T01:00',
      end_local: '2026-10-25T02:00',
      starts_at: '2026-10-24T23:00:00Z',
      ends_at: '2026-10-25T00:00:00Z',
    });
    const o = instance({
      original_start: '2026-10-24T23:00:00Z',
      start: '2026-10-24T23:00:00Z',
      end: '2026-10-25T00:00:00Z',
    });
    const plan = planChange(
      change(o, 'resize', '2026-10-24T23:00:00Z', '2026-10-25T01:30:00Z'),
      master,
      'all',
    );
    expect(plan).toEqual({ kind: 'refuse', code: 'repeated_local_time' });
  });
});

describe('isStale', () => {
  it('is false when the fetched event matches the one-off', () => {
    expect(isStale(occurrence(), event())).toBe(false);
  });
  it('is true when the one-off moved, changed zone or was cancelled', () => {
    expect(isStale(occurrence(), event({ starts_at: '2026-03-24T09:00:00Z' }))).toBe(true);
    expect(isStale(occurrence(), event({ ends_at: '2026-03-23T12:00:00Z' }))).toBe(true);
    expect(isStale(occurrence(), event({ timezone: 'UTC' }))).toBe(true);
    expect(isStale(occurrence(), event({ cancelled: true }))).toBe(true);
  });
  it('compares an all-day one-off by dates', () => {
    expect(isStale(allDayOccurrence(), allDayEvent())).toBe(false);
    expect(isStale(allDayOccurrence(), allDayEvent({ start_local: '2026-08-02' }))).toBe(true);
  });
  it('is false for an untouched instance', () => {
    expect(isStale(instance(), series())).toBe(false);
  });
  it('is true when the master stopped repeating or its time or length changed', () => {
    expect(isStale(instance(), series({ rrule: null }))).toBe(true);
    expect(isStale(instance(), series({ start_local: '2026-03-02T11:00' }))).toBe(true);
    expect(isStale(instance(), series({ ends_at: '2026-03-02T11:00:00Z' }))).toBe(true);
  });
  it('is true when a moved override appeared with other times', () => {
    const moved = {
      id: 1,
      original_start: '2026-03-23T09:00:00Z',
      kind: 'moved' as const,
      starts_at: '2026-03-24T09:00:00Z',
      ends_at: '2026-03-24T10:00:00Z',
      start_local: '2026-03-24T10:00',
      end_local: '2026-03-24T11:00',
      note: null,
    };
    expect(isStale(instance(), series({ overrides: [moved] }))).toBe(true);
  });
  it('is false when the override matches what the grid shows', () => {
    const o = instance({ start: '2026-03-24T09:00:00Z', end: '2026-03-24T10:00:00Z' });
    const moved = {
      id: 1,
      original_start: '2026-03-23T09:00:00Z',
      kind: 'moved' as const,
      starts_at: '2026-03-24T09:00:00Z',
      ends_at: '2026-03-24T10:00:00Z',
      start_local: '2026-03-24T10:00',
      end_local: '2026-03-24T11:00',
      note: null,
    };
    expect(isStale(o, series({ overrides: [moved] }))).toBe(false);
  });
  it('is true when the occurrence was cancelled or skipped meanwhile', () => {
    const gone = {
      id: 2,
      original_start: '2026-03-23T09:00:00Z',
      kind: 'cancelled' as const,
      starts_at: null,
      ends_at: null,
      start_local: null,
      end_local: null,
      note: null,
    };
    expect(isStale(instance(), series({ overrides: [gone] }))).toBe(true);
  });
});
