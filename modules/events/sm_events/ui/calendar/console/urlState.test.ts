import { describe, expect, it } from 'vitest';
import type { CalendarState } from '../types';
import { readState, writeState } from './urlState';

const ALL = ['c1', 'c2', 'c3'];

describe('urlState', () => {
  it('round-trips every field', () => {
    const state: CalendarState = {
      view: 'week',
      date: '2026-03-30',
      tzMode: 'mine',
      calendars: ['c1', 'c3'],
      categories: ['k1', 'k2'],
      types: ['event'],
      sources: ['records:dates'],
    };
    const search = writeState(state, ALL);
    expect(search).toBe(
      '?view=week&date=2026-03-30&tz=mine&calendar=c1&calendar=c3&category=k1&category=k2&type=event&source=records%3Adates',
    );
    expect(readState(search)).toEqual(state);
  });

  it('leaves the calendar filter out while every calendar is shown', () => {
    const search = writeState(
      {
        view: 'month',
        date: '2026-03-01',
        tzMode: 'calendar',
        calendars: ALL,
        categories: [],
        types: [],
        sources: [],
      },
      ALL,
    );
    expect(search).toBe('?view=month&date=2026-03-01&tz=calendar');
    expect(readState(search)).toEqual({ view: 'month', date: '2026-03-01', tzMode: 'calendar' });
  });

  it('ignores unknown views, malformed dates and unknown time zone modes', () => {
    expect(readState('?view=year&date=2026-13-40&tz=utc')).toEqual({});
    expect(readState('?date=soon')).toEqual({});
    expect(readState('')).toEqual({});
  });

  it('reads the view and date alone', () => {
    expect(readState('?view=list&date=2026-03-30')).toEqual({ view: 'list', date: '2026-03-30' });
  });
});
