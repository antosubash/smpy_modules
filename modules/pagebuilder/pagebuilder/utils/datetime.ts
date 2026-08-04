/** Conversions between ISO strings and `<input type="datetime-local">` values. */

/**
 * Format an ISO string (with offset, from the server) into the local
 * ``YYYY-MM-DDTHH:mm`` shape an ``<input type="datetime-local">``
 * expects. Returns ``""`` for null so the input renders empty.
 */
export function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Inverse of toLocalInput: take whatever a ``datetime-local`` produced
 * (a naive local-time string) and emit an ISO string with offset that
 * round-trips through the server's UTC normalisation.
 */
export function fromLocalInput(value: string | null): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
