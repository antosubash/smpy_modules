/**
 * A timestamp as date and time, in the console's locale.
 *
 * `locale` is `useT().locale`, passed rather than left to the browser: a
 * German console on an English browser would otherwise date every row the
 * English way (#189). `options` default to `toLocaleString`'s own (date and
 * time). Empty for a missing or unparseable value, never "Invalid Date".
 */
export function formatTimestamp(
  iso: string | null | undefined,
  locale: string | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(locale, options);
}
