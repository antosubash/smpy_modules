import { describe, expect, it } from 'vitest';
import type { EventDetail, Occurrence } from '../../utils/types-events';
import type { OccurrenceChange } from '../types';
import { isSeries, isStale, planChange } from './writes';

const VIENNA = 'Europe/Vienna';

const event = (extra: Partial<EventDetail> = {}): EventDetail =>
  ({
    id: 'e1',
    revision: 7,
    all_day: false,
    timezone: VIENNA,
    starts_at: '2026-03-23T09:00:00Z',
    ends_at: '2026-03-23T10:00:00Z',
    start_local: '2026-03-23T10:00',
    end_local: '2026-03-23T11:00',
    rrule: null,
    cancelled: false,
    overrides: [],
    ...extra,
  }) as EventDetail;

const occurrence = (extra: Partial<Occurrence> = {}): Occurrence => ({
  source: 'events',
  key: 'e1:0',
  calendar_id: 'c1',
  start: '2026-03-23T09:00:00Z',
  end: '2026-03-23T10:00:00Z',
  all_day: false,
  timezone: VIENNA,
  start_date: null,
  end_date: null,
  title: 'Planning',
  lang: 'en',
  color: '#2563eb',
  url: null,
  status: 'confirmed',
  type: 'event',
  editable: true,
  event_id: 'e1',
  original_start: null,
  event_status: 'draft',
  ...extra,
});

/** A weekly Monday 10:00 Vienna series starting 2026-03-02, one hour long. */
const series = (extra: Partial<EventDetail> = {}) =>
  event({
    rrule: 'FREQ=WEEKLY;BYDAY=MO',
    starts_at: '2026-03-02T09:00:00Z',
    ends_at: '2026-03-02T10:00:00Z',
    start_local: '2026-03-02T10:00',
    end_local: '2026-03-02T11:00',
    ...extra,
  });
const instance = (extra: Partial<Occurrence> = {}) =>
  occurrence({ original_start: '2026-03-23T09:00:00Z', ...extra });

const change = (
  o: Occurrence,
  kind: OccurrenceChange['kind'],
  start: string,
  end: string,
  allDay = false,
): OccurrenceChange => ({ occurrence: o, kind, start, end, allDay });

const allDayOccurrence = (extra: Partial<Occurrence> = {}) =>
  occurrence({
    all_day: true,
    start: '2026-07-31T22:00:00Z',
    end: '2026-08-03T22:00:00Z',
    start_date: '2026-08-01',
    end_date: '2026-08-04',
    ...extra,
  });
const allDayEvent = (extra: Partial<EventDetail> = {}) =>
  event({
    all_day: true,
    starts_at: '2026-07-31T22:00:00Z',
    ends_at: '2026-08-03T22:00:00Z',
    start_local: '2026-08-01',
    end_local: '2026-08-03',
    ...extra,
  });

describe('one-off', () => {
  it('moved in a New York grid writes Vienna wall clock', () => {
    const o = occurrence();
    // The grid (New York) showed 05:00 EDT; the drop is 2026-03-30 05:00 EDT = 09:00Z.
    const plan = planChange(
      change(o, 'move', '2026-03-30T09:00:00Z', '2026-03-30T10:00:00Z'),
      event(),
      'one',
    );
    expect(plan).toEqual({
      kind: 'patch',
      eventId: 'e1',
      body: {
        expected_revision: 7,
        times: {
          all_day: false,
          timezone: VIENNA,
          start: '2026-03-30T11:00',
          end: '2026-03-30T12:00',
        },
      },
    });
  });

  it('a move keeps the exact duration whatever end the grid reports', () => {
    const o = occurrence({ end: '2026-03-23T11:00:00Z' });
    const ev = event({ ends_at: '2026-03-23T11:00:00Z', end_local: '2026-03-23T12:00' });
    // The grid's end is a wall-clock shift (+7d) and would be 1h short across the change.
    const plan = planChange(
      change(o, 'move', '2026-03-28T09:00:00Z', '2026-03-28T10:00:00Z'),
      ev,
      'one',
    );
    expect(plan).toMatchObject({
      kind: 'patch',
      body: { times: { start: '2026-03-28T10:00', end: '2026-03-28T12:00' } },
    });
    const crossing = planChange(
      change(o, 'move', '2026-03-29T00:30:00Z', '2026-03-29T01:30:00Z'),
      ev,
      'one',
    );
    // 00:30Z = 01:30 CET; two hours later is 02:30Z = 04:30 CEST, because 02:00 does not exist.
    expect(crossing).toMatchObject({
      body: { times: { start: '2026-03-29T01:30', end: '2026-03-29T04:30' } },
    });
  });

  it('a resize changes only the end', () => {
    const plan = planChange(
      change(occurrence(), 'resize', '2026-03-23T09:00:00Z', '2026-03-23T11:30:00Z'),
      event(),
      'one',
    );
    expect(plan).toMatchObject({
      body: { times: { start: '2026-03-23T10:00', end: '2026-03-23T12:30' } },
    });
  });

  it('an all-day move shifts dates and keeps the inclusive end', () => {
    const plan = planChange(
      change(allDayOccurrence(), 'move', '2026-08-03', '2026-08-06', true),
      allDayEvent(),
      'one',
    );
    expect(plan).toMatchObject({
      kind: 'patch',
      body: { times: { all_day: true, start: '2026-08-03', end: '2026-08-05' } },
    });
  });

  it('an all-day move over a clock change is date arithmetic', () => {
    const o = allDayOccurrence({ start_date: '2026-03-28', end_date: '2026-03-29' });
    const ev = allDayEvent({ start_local: '2026-03-28', end_local: '2026-03-28' });
    const plan = planChange(change(o, 'move', '2026-03-29', '2026-03-30', true), ev, 'one');
    expect(plan).toMatchObject({ body: { times: { start: '2026-03-29', end: '2026-03-29' } } });
  });

  it('an all-day resize changes only the end', () => {
    const plan = planChange(
      change(allDayOccurrence(), 'resize', '2026-08-01', '2026-08-06', true),
      allDayEvent(),
      'one',
    );
    expect(plan).toMatchObject({ body: { times: { start: '2026-08-01', end: '2026-08-05' } } });
  });

  it('refuses the second 02:30 of the autumn change and allows the first', () => {
    const o = occurrence({ start: '2026-10-20T09:00:00Z', end: '2026-10-20T10:00:00Z' });
    const second = planChange(
      change(o, 'move', '2026-10-25T01:30:00Z', '2026-10-25T02:30:00Z'),
      event(),
      'one',
    );
    expect(second).toEqual({ kind: 'refuse', code: 'repeated_local_time' });
    // A 15-minute event, so both edges stay inside the first pass through 02:xx.
    const short = occurrence({ start: '2026-10-20T09:00:00Z', end: '2026-10-20T09:15:00Z' });
    const first = planChange(
      change(short, 'move', '2026-10-25T00:30:00Z', '2026-10-25T00:45:00Z'),
      event(),
      'one',
    );
    expect(first).toMatchObject({ body: { times: { start: '2026-10-25T02:30' } } });
  });

  it('refuses an end that lands on the repeated hour', () => {
    const plan = planChange(
      change(occurrence(), 'resize', '2026-03-23T09:00:00Z', '2026-10-25T01:30:00Z'),
      event(),
      'one',
    );
    expect(plan).toEqual({ kind: 'refuse', code: 'repeated_local_time' });
  });

  it('a spring drop in a New York grid never reaches a nonexistent Vienna time', () => {
    // 2026-03-29T01:30Z is 03:30 CEST: the instant exists, so the wall time does.
    const plan = planChange(
      change(occurrence(), 'move', '2026-03-29T01:30:00Z', '2026-03-29T02:30:00Z'),
      event(),
      'one',
    );
    expect(plan).toMatchObject({ body: { times: { start: '2026-03-29T03:30' } } });
  });
});

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
    const o = instance({ original_start: '2026-03-22T01:30:00Z' });
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

describe('reschedule (the Move dialog)', () => {
  it('takes both ends as given', () => {
    const plan = planChange(
      change(occurrence(), 'reschedule', '2026-03-30T09:00:00Z', '2026-03-30T12:00:00Z'),
      event(),
      'one',
    );
    expect(plan).toMatchObject({
      body: { times: { start: '2026-03-30T11:00', end: '2026-03-30T14:00' } },
    });
  });
});

describe('isSeries', () => {
  it('is an original start', () => {
    expect(isSeries(instance())).toBe(true);
    expect(isSeries(occurrence())).toBe(false);
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
