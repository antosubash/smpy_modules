import { describe, expect, it } from 'vitest';
import { isSeries, planChange } from './writes';
import {
  allDayEvent,
  allDayOccurrence,
  change,
  event,
  instance,
  occurrence,
  VIENNA,
} from './writes-fixtures';

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
