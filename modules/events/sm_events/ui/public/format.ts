/** Text for the public screens. An event's own clock is shown as it is: its local fields are
 *  formatted in UTC so the browser's zone never touches them. */
import { browserZone } from '../utils/zones';

const parts = (local: string) => {
  const [date = '', time = ''] = local.split('T');
  const [y = 0, m = 1, d = 1] = date.split('-').map(Number);
  const [hh = 0, mm = 0] = time.split(':').map(Number);
  return new Date(Date.UTC(y, m - 1, d, hh, mm));
};

export function monthName(month: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parts(`${month}-01`));
}

const dateOf = (local: string, locale: string, style: 'medium' | 'full' = 'medium') =>
  new Intl.DateTimeFormat(locale, { dateStyle: style, timeZone: 'UTC' }).format(parts(local));

/** A timed span on the event's own clock: one date, then the times. */
export function localSpan(start: string, end: string, locale: string): string {
  const time = new Intl.DateTimeFormat(locale, { timeStyle: 'short', timeZone: 'UTC' });
  const sameDay = start.slice(0, 10) === end.slice(0, 10);
  const head = `${dateOf(start, locale)}, ${time.format(parts(start))}`;
  if (start === end) return head;
  return sameDay
    ? `${head} – ${time.format(parts(end))}`
    : `${head} – ${dateOf(end, locale)}, ${time.format(parts(end))}`;
}

/** An all-day span: dates only, the last day inclusive. */
export function daySpan(first: string, last: string | null, locale: string): string {
  const a = dateOf(first, locale);
  return last && last > first ? `${a} – ${dateOf(last, locale)}` : a;
}

/** The instants in the visitor's own zone, or `null` when it is the event's zone (or the event
 *  is all-day) and the hint would repeat what is already shown. */
export function viewerSpan(
  startIso: string,
  endIso: string,
  eventZone: string,
  locale: string,
  mine: string = browserZone(),
): string | null {
  if (mine === eventZone) return null;
  const format = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: mine,
  });
  const own = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: eventZone,
  });
  const a = new Date(startIso);
  const b = new Date(endIso);
  const text = format.formatRange(a, b);
  return text === own.formatRange(a, b) ? null : text;
}
