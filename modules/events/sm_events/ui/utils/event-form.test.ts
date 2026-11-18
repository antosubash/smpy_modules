import { describe, expect, it } from 'vitest';
import {
  blankText,
  changesSchedule,
  clockOf,
  emptyForm,
  toCreate,
  today,
  toPatch,
  withAllDay,
} from './event-form';

const base = () => {
  const form = emptyForm('Europe/Vienna', ['en', 'de']);
  form.start = '2026-07-01T10:00';
  form.end = '2026-07-01T11:00';
  form.texts.en = { ...blankText(true), title: 'Concert', slug: 'concert' };
  return form;
};

describe('event form', () => {
  it('creates only the languages that are present', () => {
    const body = toCreate(base(), 'c1');
    expect(Object.keys(body.texts)).toEqual(['en']);
    expect(body.times).toEqual({
      all_day: false,
      timezone: 'Europe/Vienna',
      start: '2026-07-01T10:00',
      end: '2026-07-01T11:00',
    });
    expect(body.rrule).toBeNull();
  });

  it('patches only what changed, and deletes a removed language with null', () => {
    const before = base();
    before.texts.de = { ...blankText(true), title: 'Konzert' };
    const after = structuredClone(before);
    expect(toPatch(before, after, 2)).toBeNull();
    after.venue_name = 'Hall';
    after.texts.de = blankText();
    after.texts.en = { ...blankText(true), title: 'Concert!' };
    const patch = toPatch(before, after, 2);
    expect(patch?.expected_revision).toBe(2);
    expect(patch?.venue_name).toBe('Hall');
    expect(patch?.times).toBeUndefined();
    expect(patch?.texts?.de).toBeNull();
    expect(patch?.texts?.en?.title).toBe('Concert!');
  });

  it('switches all-day with an inclusive end and back', () => {
    const allDay = withAllDay(base(), true);
    expect([allDay.start, allDay.end]).toEqual(['2026-07-01', '2026-07-01']);
    const timed = withAllDay(allDay, false);
    expect([timed.start, timed.end]).toEqual(['2026-07-01T09:00', '2026-07-01T10:00']);
  });

  it('knows when the schedule changed', () => {
    const before = base();
    const after = { ...before, venue_name: 'Hall' };
    expect(changesSchedule(before, after)).toBe(false);
    expect(changesSchedule(before, { ...after, rrule: 'FREQ=DAILY' })).toBe(true);
    expect(changesSchedule(before, { ...after, timezone: 'UTC' })).toBe(true);
  });

  it("restores the clock times from before 'all day' was ticked", () => {
    const form = base();
    form.start = '2026-07-01T14:30';
    form.end = '2026-07-01T16:45';
    const remembered = clockOf(form);
    expect(remembered).toEqual({ start: '14:30', end: '16:45' });
    const allDay = withAllDay(form, true);
    expect(clockOf(allDay)).toBeUndefined();
    const timed = withAllDay(allDay, false, remembered);
    expect([timed.start, timed.end]).toEqual(['2026-07-01T14:30', '2026-07-01T16:45']);
    expect(withAllDay(allDay, false).start).toBe('2026-07-01T09:00');
  });

  it("takes today's date on the calendar's clock, not the browser's", () => {
    const instant = new Date('2026-07-01T23:30:00Z');
    expect(today('Europe/Vienna', instant)).toBe('2026-07-02');
    expect(today('America/Los_Angeles', instant)).toBe('2026-07-01');
    expect(today('Pacific/Auckland', instant)).toBe('2026-07-02');
    const form = emptyForm('Pacific/Kiritimati', ['en'], instant);
    expect([form.start, form.end]).toEqual(['2026-07-02T09:00', '2026-07-02T10:00']);
    expect(emptyForm('Not/AZone', ['en'], instant).start).toMatch(/^\d{4}-\d{2}-\d{2}T09:00$/);
  });
});
