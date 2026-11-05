/** Pure helpers of the campaign report screen. */

/** `part / whole`, or null when there is no whole. Never clamps: the server guarantees <= 1 (B5). */
export function rate(part: number, whole: number): number | null {
  return whole > 0 ? part / whole : null;
}

export function formatRate(r: number | null, locale: string): string | null {
  if (r === null) return null;
  return new Intl.NumberFormat(locale, {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(r);
}

/** A bucket's label in UTC, matching how the server buckets (B6). */
export function bucketLabel(at: string, bucket: 'hour' | 'day', locale: string): string {
  const date = new Date(at);
  const day = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(
    date,
  );
  if (bucket === 'day') return day;
  // Take the digits from the parts: some locales wrap the hour in words ("23 Uhr", "23 h").
  const parts = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: 'UTC',
  }).formatToParts(date);
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '00';
  return `${day} ${pick('hour').padStart(2, '0')}:${pick('minute').padStart(2, '0')}`;
}

const STARTED = new Set(['sending', 'paused', 'sent', 'cancelled']);

/** Whether the campaign has begun sending, so a report means something. */
export function hasStarted(c: { status: string; started_at: string | null }): boolean {
  return c.started_at !== null && STARTED.has(c.status);
}
