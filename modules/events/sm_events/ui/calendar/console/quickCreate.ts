/** The quick-create form's maths: a grid slot as wall clock in a calendar's zone, the same
 *  moment in another zone, the request body and the "More options" link. Pure. */
import { emptyForm, type FormState, toCreate } from '../../utils/event-form';
import type { EventCreate } from '../../utils/types-events';
import { addDays, isNonexistent, toInstant, toLocal } from '../time/zones';
import type { CreateSlot } from '../types';

export type Clock = { allDay: boolean; start: string; end: string };

const dateOf = (wall: string): string => wall.slice(0, 10);

/** A slot as the form shows it: timed edges as wall clock in `zone`, an all-day span as dates
 *  whose end is the last day it covers (the slot's own end is exclusive). */
export function clockOf(slot: CreateSlot, zone: string): Clock {
  if (slot.allDay) {
    const last = addDays(slot.end, -1);
    return { allDay: true, start: slot.start, end: [slot.start, last].sort().at(-1) ?? slot.start };
  }
  return { allDay: false, start: toLocal(slot.start, zone), end: toLocal(slot.end, zone) };
}

/** The same moment in another calendar's zone. An all-day span is dates, which no zone moves. */
export function reexpress(clock: Clock, from: string, to: string): Clock {
  if (clock.allDay || from === to) return clock;
  return {
    allDay: false,
    start: toLocal(toInstant(clock.start, from), to),
    end: toLocal(toInstant(clock.end, from), to),
  };
}

/** Ticking "all day" keeps the dates; unticking restores the clock times from before, or 09:00 to 10:00. */
export function withAllDay(clock: Clock, allDay: boolean, remembered?: Clock): Clock {
  if (clock.allDay === allDay) return clock;
  if (allDay) return { allDay, start: dateOf(clock.start), end: dateOf(clock.end) };
  const time = (wall: string | undefined, fallback: string) => wall?.slice(11) || fallback;
  return {
    allDay,
    start: `${clock.start}T${time(remembered?.start, '09:00')}`,
    end: `${clock.end}T${time(remembered?.end, '10:00')}`,
  };
}

/** What is wrong with the times, by field, before anything is sent. */
export function timeProblems(
  clock: Clock,
  zone: string,
): { start?: 'skipped'; end?: 'order' | 'skipped' } {
  const found: ReturnType<typeof timeProblems> = {};
  if (clock.allDay) {
    if (clock.end < clock.start) found.end = 'order';
    return found;
  }
  if (isNonexistent(clock.start, zone)) found.start = 'skipped';
  if (isNonexistent(clock.end, zone)) found.end = 'skipped';
  else if (clock.end <= clock.start) found.end = 'order';
  return found;
}

export function createBody(
  clock: Clock,
  calendarId: string,
  zone: string,
  locale: string,
  title: string,
): EventCreate {
  const form: FormState = emptyForm(zone, [locale]);
  const text = form.texts[locale];
  const filled: FormState = {
    ...form,
    all_day: clock.allDay,
    start: clock.start,
    end: clock.end,
    texts: text ? { [locale]: { ...text, title } } : form.texts,
  };
  return toCreate(filled, calendarId);
}

/** The new-event editor, with what the form holds so far. Every part is encoded; the server
 *  validates the lot and drops what it cannot vouch for. */
export function editorHref(editorUrl: string, calendarId: string, clock: Clock, title: string) {
  const part = (name: string, value: string) => `${name}=${encodeURIComponent(value)}`;
  const query = [
    part('calendar', calendarId),
    part('all_day', clock.allDay ? '1' : '0'),
    part('start', clock.start),
    part('end', clock.end),
    ...(title.trim() ? [part('title', title.trim())] : []),
  ];
  return `${editorUrl}/new?${query.join('&')}`;
}
