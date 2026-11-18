/** The one owner of conversion between instants and wall clock: Temporal, in a *named*
 *  zone. Nothing in the module parses a local time with `Date` or reads the browser's offset
 *  to convert; the event's own zone is the only one a write is expressed in. */
import { Temporal } from 'temporal-polyfill';

/** The browser's zone, `UTC` where it cannot say. */
export const browserZone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
};

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

/** Today's date on the clock of a zone (the calendar's own, not the browser's); the
 *  browser's day for a zone it does not know. */
export function todayIn(timeZone?: string, now: Date = new Date()): string {
  const at = Temporal.Instant.fromEpochMilliseconds(now.getTime());
  try {
    return at
      .toZonedDateTimeISO(timeZone || browserZone())
      .toPlainDate()
      .toString();
  } catch {
    return at.toZonedDateTimeISO(browserZone()).toPlainDate().toString();
  }
}

const offsetLabel = (zoned: Temporal.ZonedDateTime): string => {
  const minutes = Math.round(zoned.offsetNanoseconds / 60_000_000_000);
  const abs = Math.abs(minutes);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `UTC${minutes < 0 ? '-' : '+'}${hh}:${mm}`;
};

/** "UTC+02:00" that `timeZone` has at the instant `instantIso` (the event's zone, never the
 *  browser's); `null` for a bad instant or a zone the runtime does not know. */
export function utcOffsetAt(instantIso: string, timeZone: string): string | null {
  try {
    return offsetLabel(Temporal.Instant.from(instantIso).toZonedDateTimeISO(timeZone));
  } catch {
    return null;
  }
}

/** "UTC+02:00" for the wall clock `local` in `timeZone` (the earlier offset on a repeated
 *  hour, the one after the gap on a skipped one); `null` for a bad time or an unknown zone. */
export function utcOffset(local: string, timeZone: string): string | null {
  try {
    return offsetLabel(Temporal.PlainDateTime.from(local).toZonedDateTime(timeZone));
  } catch {
    return null;
  }
}

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

/** Whether `text` is a date and time (`YYYY-MM-DDTHH:MM`, seconds optional), or a date when
 *  `dateOnly`. A browser input can hold more than that (a six-digit year), and Temporal
 *  throws on it, so user input goes through here before any conversion. */
export function isWallTime(text: string, dateOnly = false): boolean {
  if (dateOnly) return isDate(text);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(text)) return false;
  try {
    return Temporal.PlainDateTime.from(text, { overflow: 'reject' }) !== null;
  } catch {
    return false;
  }
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
