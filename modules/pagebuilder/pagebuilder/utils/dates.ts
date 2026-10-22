import { intlLocale } from './locale';

/** A date and time with no `Z` or `±hh:mm` after it. */
const NAIVE = /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

/**
 * A timestamp as date and time, in the console's locale.
 *
 * `locale` is `useT().locale`, passed rather than left to the browser: a
 * German console on an English browser would otherwise date every row the
 * English way (#189). `options` default to `toLocaleString`'s own (date and
 * time). Empty for a missing or unparseable value, never "Invalid Date".
 *
 * A timestamp with no zone (`2026-10-22T08:33:14.17`) is UTC: that is how
 * the server stores every instant, and a schema typed plain `datetime`
 * (revisions, snapshots, layouts) sends it without the `Z`. `new Date` would
 * otherwise read it as the viewer's local time and shift it by their offset.
 */
export function formatTimestamp(
  iso: string | null | undefined,
  locale: string | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!iso) return '';
  const date = parseInstant(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(intlLocale(locale), options);
}

/** *iso* as a `Date`, reading a zone-less timestamp as UTC (see above). */
export function parseInstant(iso: string): Date {
  return new Date(NAIVE.test(iso) ? `${iso}Z` : iso);
}
