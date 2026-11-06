/** Small, pure helpers for the send dialog and the sending panel. */

import type { Progress } from './types';

/** Days still needed at the daily rate for what is queued or in flight; null when
 *  nothing is left or no rate is known. */
export function daysLeft(p: Progress): number | null {
  const left = p.queued + p.sending;
  if (left <= 0 || p.daily_rate <= 0) return null;
  return Math.ceil(left / p.daily_rate);
}

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** A `datetime-local` value (the browser's local time) as an ISO UTC instant; null
 *  when empty or not a real date and time (no rollover: 2026-13-45 is refused). */
export function toUtcIso(local: string): string | null {
  const m = LOCAL.exec(local);
  if (!m) return null;
  const [y, mo, d, h, mi, s] = m.slice(1).map((v) => Number(v ?? 0));
  const date = new Date(y, mo - 1, d, h, mi, s);
  const same =
    date.getFullYear() === y &&
    date.getMonth() === mo - 1 &&
    date.getDate() === d &&
    date.getHours() === h &&
    date.getMinutes() === mi;
  return same ? date.toISOString() : null;
}

/** An instant for a reader: medium date, short time, in the console's language. */
export function formatWhen(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
