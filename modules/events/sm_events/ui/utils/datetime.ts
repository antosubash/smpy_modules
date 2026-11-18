/** Wall-clock text from the API (`YYYY-MM-DDTHH:MM`, or a date) shown in the
 *  event's own clock: the digits are never converted to another zone. */
import { dateLocale } from './recurrence';

export { browserZone, utcOffset, utcOffsetAt } from './zones';

const WALL = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/;

/** The wall clock as a UTC `Date`, to be formatted with `timeZone: 'UTC'` so the digits survive. */
export function wallDate(wall: string): Date | null {
  return parts(wall)?.at ?? null;
}

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

// --- Text for the public screens: the event's own clock, in the page's language. ---------------

const at = (wall: string): Date => wallDate(wall) ?? new Date(Number.NaN);

/** "July 2026" for `YYYY-MM`. */
export function monthName(month: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(at(`${month}-01`));
}

const dateOf = (wall: string, locale: string) =>
  new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(at(wall));

/** A timed span on the event's own clock: one date, then the times. */
export function localSpan(start: string, end: string, locale: string): string {
  const time = new Intl.DateTimeFormat(locale, { timeStyle: 'short', timeZone: 'UTC' });
  const head = `${dateOf(start, locale)}, ${time.format(at(start))}`;
  if (start === end) return head;
  return start.slice(0, 10) === end.slice(0, 10)
    ? `${head} – ${time.format(at(end))}`
    : `${head} – ${dateOf(end, locale)}, ${time.format(at(end))}`;
}

/** An all-day span: dates only, the last day inclusive. */
export function daySpan(first: string, last: string | null, locale: string): string {
  const a = dateOf(first, locale);
  return last && last > first ? `${a} – ${dateOf(last, locale)}` : a;
}

/** A moment's day in the viewer's own zone and the console's language ("18 Nov 2026",
 *  "18.11.2026"): for server instants such as a link's creation time. */
export function formatDay(iso: string, locale?: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return new Intl.DateTimeFormat(dateLocale(locale), { dateStyle: 'medium' }).format(at);
}
