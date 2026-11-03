import { intlLocale } from './locale';

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** ISO-with-offset → the naive local string a `datetime-local` input wants.
 *
 * Includes seconds (`HH:MM:SS`) so a value that carries them survives an
 * open-and-save round trip unchanged — an input truncated to `HH:MM` silently
 * zeroes them on every save. Pair with `step="1"` on the input itself, or the
 * browser's own UI never offers a seconds field to type into. */
export function isoToLocalInput(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '';
  const date = `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
  const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  return `${date}T${time}`;
}

/** A `datetime-local` string → ISO 8601 carrying the browser's own offset.
 *
 * Never returns a naive value for input the browser can parse: the server
 * refuses one rather than guessing a zone, and guessing UTC here would shift
 * every timestamp by the viewer's offset. Unparseable text is handed back
 * untouched so the server's message, not a silent fallback, is what the
 * person sees. */
export function localInputToIso(local: string): string {
  const parsed = new Date(local);
  if (Number.isNaN(parsed.getTime())) return local;
  const minutes = -parsed.getTimezoneOffset();
  const sign = minutes < 0 ? '-' : '+';
  const abs = Math.abs(minutes);
  const offset = `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  const date = `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
  const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  return `${date}T${time}${offset}`;
}

/**
 * ISO datetime (with offset) → date + short time in `locale`, the console's
 * (`useT().locale`) — never the browser's, which need not match it (#189).
 *
 * Shared between a schema `datetime` field's cell (`RecordCell`) and the
 * envelope's own fixed timestamps (`published_at`/`updated_at`/`created_at`,
 * design §9) — both are ISO-with-offset on the wire, so the same
 * presentation belongs on both (a raw ISO string beside a formatted field
 * reads as two different clocks on one row).
 *
 * Unparseable input is handed back unchanged, same as a `datetime` field's
 * own fallback — the point is never to substitute a value for one the
 * browser's `Date` rejects.
 */
export function formatDateTime(value: string, locale: string | undefined): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const options = { dateStyle: 'medium', timeStyle: 'short' } as const;
  return new Intl.DateTimeFormat(intlLocale(locale), options).format(parsed);
}

/** A bare calendar day ("YYYY-MM-DD", design §7.3) has no timezone of its
 *  own: anchor it at UTC midnight and format in UTC, so the displayed day
 *  cannot shift for a viewer west of UTC. Unparseable input comes back as is.
 *  `locale` as for `formatDateTime`. */
export function formatCalendarDate(value: string, locale: string | undefined): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  const options = { dateStyle: 'medium', timeZone: 'UTC' } as const;
  return new Intl.DateTimeFormat(intlLocale(locale), options).format(parsed);
}
