/**
 * The editor's when-line for an event card: the event's own timezone, the editor's language.
 *
 * Only a preview of what the email will say. The server's line (`content/render/event_card.py`)
 * is the one that is sent, formatted with Babel and the tzdata zone abbreviation, so this need
 * not match it byte for byte; it has the same shape.
 */

import type { EventCardHit } from './types';

export type WhenInput = Pick<
  EventCardHit,
  'starts_at' | 'ends_at' | 'all_day' | 'start_date' | 'end_date' | 'timezone'
>;

const ONE_DAY_MS = 86_400_000;

function day(date: Date, locale: string, timeZone: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeZone }).format(date);
}

function time(date: Date, locale: string, timeZone: string): { clock: string; zone: string } {
  const parts = new Intl.DateTimeFormat(locale, {
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
    timeZoneName: 'short',
  }).formatToParts(date);
  const zone = parts.find((p) => p.type === 'timeZoneName')?.value ?? timeZone;
  const clock = parts
    .filter((p) => p.type !== 'timeZoneName')
    .map((p) => p.value)
    .join('')
    .trim();
  return { clock, zone };
}

/** `YYYY-MM-DD` as a UTC-noon instant, so formatting it in UTC keeps the date. */
function calendarDay(value: string): Date {
  return new Date(`${value}T12:00:00Z`);
}

export function formatEventWhen(p: WhenInput, locale: string): string {
  if (p.all_day && p.start_date && p.end_date) {
    const first = calendarDay(p.start_date);
    const last = new Date(calendarDay(p.end_date).getTime() - ONE_DAY_MS);
    const from = day(first, locale, 'UTC');
    return last <= first ? from : `${from} – ${day(last, locale, 'UTC')}`;
  }
  const start = new Date(p.starts_at);
  const end = new Date(p.ends_at);
  const a = time(start, locale, p.timezone);
  const b = time(end, locale, p.timezone);
  const startDay = day(start, locale, p.timezone);
  const endDay = day(end, locale, p.timezone);
  if (startDay === endDay) {
    const span =
      a.zone === b.zone
        ? `${a.clock}–${b.clock} ${b.zone}`
        : `${a.clock} ${a.zone}–${b.clock} ${b.zone}`;
    return `${startDay}, ${span}`;
  }
  return `${startDay}, ${a.clock} ${a.zone} – ${endDay}, ${b.clock} ${b.zone}`;
}
