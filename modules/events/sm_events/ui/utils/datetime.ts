/** Wall-clock text from the API (`YYYY-MM-DDTHH:MM`, or a date) shown in the
 *  event's own clock: the digits are never converted to another zone. */
import { dateLocale } from './recurrence';

export { browserZone, utcOffset, utcOffsetAt } from './zones';

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
