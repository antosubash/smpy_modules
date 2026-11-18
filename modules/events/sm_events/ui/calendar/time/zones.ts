/** Every conversion between instants and wall clock goes through here, on Temporal,
 *  in a *named* zone. Nothing in the calendar parses a local time with `Date` or reads
 *  the browser's offset. The event's own zone is the only one a write is expressed in. */
import { Temporal } from 'temporal-polyfill';
import type { CalendarInfo } from '../types';

export type TzMode = 'calendar' | 'mine';

export const browserTimeZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone;

/** The grid's zone: the one shown calendar's own, else the tenant's; or the browser's. */
export function gridTimeZone(
  mode: TzMode,
  shown: CalendarInfo[],
  tenantDefault: string,
  mine: string = browserTimeZone(),
): string {
  if (mode === 'mine') return mine;
  const only = shown.length === 1 ? shown[0] : undefined;
  return only?.default_timezone || tenantDefault;
}

/** `YYYY-MM-DDTHH:MM`, with `:SS` only when the seconds are not zero. */
function wallClock(local: Temporal.PlainDateTime): string {
  const withSeconds = local.second !== 0 || local.millisecond !== 0;
  return local.toString({ smallestUnit: withSeconds ? 'second' : 'minute' });
}

export function toLocal(instantIso: string, timeZone: string): string {
  const zoned = Temporal.Instant.from(instantIso).toZonedDateTimeISO(timeZone);
  return wallClock(zoned.toPlainDateTime());
}

/** The earlier instant on a repeated hour and the later one on a gap, as the server's
 *  `zoneinfo` does (`fold=0`, shifted forward): Temporal's default `compatible`. ISO `Z`. */
export function toInstant(local: string, timeZone: string): string {
  return Temporal.PlainDateTime.from(local).toZonedDateTime(timeZone).toInstant().toString();
}

/** The instant is the second of a repeated wall time, which the server would read as the
 *  first. A real instant is never in a gap, so only the fold can make the round trip differ. */
export function isRepeatedSecond(instantIso: string, timeZone: string): boolean {
  const instant = Temporal.Instant.from(instantIso);
  const wall = instant.toZonedDateTimeISO(timeZone).toPlainDateTime();
  const back = wall.toZonedDateTime(timeZone).toInstant();
  return !back.equals(instant);
}

/** `local + (to - from)`: the difference is taken on the wall clock, not in elapsed time,
 *  so a shift across a DST change keeps the wall time the user dropped on. */
export function shiftLocal(local: string, from: string, to: string): string {
  const delta = Temporal.PlainDateTime.from(from).until(Temporal.PlainDateTime.from(to), {
    largestUnit: 'day',
  });
  return wallClock(Temporal.PlainDateTime.from(local).add(delta));
}

export const addDays = (date: string, days: number): string =>
  Temporal.PlainDate.from(date).add({ days }).toString();

/** The calendar date of an instant in a zone. */
export const dateIn = (instantIso: string, timeZone: string): string =>
  Temporal.Instant.from(instantIso).toZonedDateTimeISO(timeZone).toPlainDate().toString();

/** Today's date in a zone. */
export const todayIn = (timeZone: string): string => Temporal.Now.plainDateISO(timeZone).toString();

export const isValidTimeZone = (name: string): boolean => {
  try {
    Temporal.Now.zonedDateTimeISO(name);
    return true;
  } catch {
    return false;
  }
};

export const isDate = (text: string): boolean =>
  /^\d{4}-\d{2}-\d{2}$/.test(text) && validDate(text);

function validDate(text: string): boolean {
  try {
    return Temporal.PlainDate.from(text, { overflow: 'reject' }).toString() === text;
  } catch {
    return false;
  }
}

/** A wall time the zone's clocks skip (the spring gap): `toInstant` would move it forward,
 *  so what is sent is not what was meant. */
export function isNonexistent(local: string, timeZone: string): boolean {
  const wall = Temporal.PlainDateTime.from(local);
  const back = Temporal.PlainDateTime.from(toLocal(toInstant(local, timeZone), timeZone));
  return Temporal.PlainDateTime.compare(wall, back) !== 0;
}

/** Whole calendar days from one date to another (negative when earlier). */
export const daysBetween = (from: string, to: string): number =>
  Temporal.PlainDate.from(from).until(Temporal.PlainDate.from(to), { largestUnit: 'day' }).days;

export const sameInstant = (a: string, b: string): boolean =>
  Temporal.Instant.from(a).equals(Temporal.Instant.from(b));

/** Elapsed milliseconds from one instant to another. */
export const millisBetween = (from: string, to: string): number =>
  Temporal.Instant.from(to).epochMilliseconds - Temporal.Instant.from(from).epochMilliseconds;

export const plusMillis = (instantIso: string, millis: number): string =>
  Temporal.Instant.from(instantIso).add({ milliseconds: millis }).toString();

/** Where the server puts the occurrence of a master (wall time `masterLocal`) on the date
 *  `slotIso` falls on in the zone: a time the clocks skip is moved forward, as `zoneinfo`
 *  does, so this is the instant the occurrence read has for that slot. */
export function occurrenceInstant(slotIso: string, masterLocal: string, timeZone: string): string {
  const time = Temporal.PlainDateTime.from(masterLocal).toPlainTime().toString();
  return toInstant(`${dateIn(slotIso, timeZone)}T${time}`, timeZone);
}

/** Two wall times with the same clock reading, whatever their dates. */
export const sameTimeOfDay = (a: string, b: string): boolean =>
  Temporal.PlainDateTime.from(a).toPlainTime().equals(Temporal.PlainDateTime.from(b).toPlainTime());
