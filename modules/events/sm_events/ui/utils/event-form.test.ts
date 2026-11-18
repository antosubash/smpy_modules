import { describe, expect, it } from 'vitest';
import { blankText, changesSchedule, emptyForm, toCreate, toPatch, withAllDay } from './event-form';

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
});
