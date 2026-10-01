/**
 * A file size as a person reads it, for the media picker's grid, the
 * editor's chip and the items' accessible names (`media-api.ts` re-exports
 * it).
 */

const UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte'] as const;

/** `217 B` — the byte symbol in the layout of the viewer's `kB`. CLDR's
 *  short form for the byte is the *word* in English ("217 byte", beside
 *  "2 kB"; review 4, ux F13) and its narrow form drops the space ("217B"),
 *  so this takes the narrow symbol ("B", "o", "Б") and puts it where the
 *  short kilobyte puts its own. */
function formatWholeBytes(value: number): string {
  const format = (unit: string, unitDisplay: 'short' | 'narrow') =>
    new Intl.NumberFormat(undefined, {
      style: 'unit',
      unit,
      unitDisplay,
      maximumFractionDigits: 0,
    }).formatToParts(value);
  const narrow = format('byte', 'narrow');
  const symbol = narrow.find((part) => part.type === 'unit')?.value;
  const parts = symbol ? format('kilobyte', 'short') : narrow;
  return parts.map((part) => (part.type === 'unit' ? symbol : part.value)).join('');
}

/** `1.5 MB` in the viewer's locale — `Intl` supplies the unit words, so
 *  there is nothing here to translate. */
export function formatBytes(bytes: number): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) return formatWholeBytes(value);
  return new Intl.NumberFormat(undefined, {
    style: 'unit',
    unit: UNITS[unit],
    unitDisplay: 'short',
    maximumFractionDigits: 1,
  }).format(value);
}
