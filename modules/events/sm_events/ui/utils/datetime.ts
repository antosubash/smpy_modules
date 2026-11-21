/** Wall-clock text from the API (`YYYY-MM-DDTHH:MM`, or a date) shown in the
 *  event's own clock: the digits are never converted to another zone. */
import { dateLocale } from './recurrence';

const WALL = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/;

function parts(wall: string): { at: Date; timed: boolean } | null {
  const m = WALL.exec(wall);
  if (!m) return null;
  const [, y, mo, d, h, mi] = m;
  return {
    at: new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h ?? 0), Number(mi ?? 0))),
    timed: h !== undefined,
  };
}

/** "5 Jul 2026, 10:00" (timed) or "5 Jul 2026" (a date). */
export function formatWall(wall: string, locale?: string): string {
  const found = parts(wall);
  if (!found) return wall;
  return new Intl.DateTimeFormat(dateLocale(locale), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...(found.timed ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
    timeZone: 'UTC',
  }).format(found.at);
}

/** The offset (minutes east of UTC) `timezone` has at the UTC instant `at`. */
function offsetMinutes(timezone: string, at: number): number {
  const name =
    new Intl.DateTimeFormat('en', { timeZone: timezone, timeZoneName: 'longOffset' })
      .formatToParts(new Date(at))
      .find((part) => part.type === 'timeZoneName')?.value ?? 'GMT';
  const m = /([+-])(\d{2}):?(\d{2})?/.exec(name);
  if (!m) return 0;
  return (m[1] === '-' ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] ?? 0));
}

const label = (offset: number): string => {
  const abs = Math.abs(offset);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `UTC${offset < 0 ? '-' : '+'}${hh}:${mm}`;
};

/** "UTC+02:00" for the wall clock `wall` in `timezone`; `null` for a zone the
 *  browser does not know. Two passes settle the offset next to a clock change. */
export function utcOffset(wall: string, timezone: string): string | null {
  const found = parts(wall);
  if (!found) return null;
  try {
    const guess = found.at.getTime();
    const first = offsetMinutes(timezone, guess);
    return label(offsetMinutes(timezone, guess - first * 60_000));
  } catch {
    return null;
  }
}

/** "UTC+02:00" that `timezone` has at the instant `iso` (the event's zone, never
 *  the browser's); `null` for a bad instant or a zone the browser does not know. */
export function utcOffsetAt(iso: string, timezone: string): string | null {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  try {
    return label(offsetMinutes(timezone, at));
  } catch {
    return null;
  }
}

/** Whether the server will take `timezone` as typed: a zone the browser knows,
 *  spelled as it spells it (an alias such as "US/Eastern" counts; "europe/berlin"
 *  and the half-typed "Europe/Ber" do not). */
export function knownZone(timezone: string): boolean {
  if (timezone === 'UTC') return true;
  try {
    const resolved = new Intl.DateTimeFormat('en', { timeZone: timezone }).resolvedOptions()
      .timeZone;
    return resolved === timezone || resolved.toLowerCase() !== timezone.toLowerCase();
  } catch {
    return false;
  }
}

export const browserZone = (): string => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
};

/** A UTC instant (`publish_at`) shown on the event's own clock. */
export function formatInstant(iso: string, timezone: string, locale?: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat(dateLocale(locale), {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone,
    }).format(at);
  } catch {
    return iso;
  }
}
