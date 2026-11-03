/**
 * This browser's saved column choice per record type — the per-viewer
 * default the record list falls back to when its link carries no
 * `?columns=` (see `resolveListColumns` in `utils/listing.ts`).
 *
 * `localStorage` can be missing, full, or throw on every access (a private
 * window, blocked site data), and what it holds may be anything an older
 * build or a hand edit left there. Every read and write is therefore wrapped,
 * and anything that is not a JSON array of strings reads as "nothing saved",
 * which means the default columns — never an error.
 */

const PREFIX = 'sm_records.list_columns.';

export function columnStorageKey(typeKey: string): string {
  return `${PREFIX}${typeKey}`;
}

export function readSavedColumns(typeKey: string): string[] | null {
  try {
    const raw = window.localStorage.getItem(columnStorageKey(typeKey));
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.every((key) => typeof key === 'string')) {
      return parsed as string[];
    }
    return null;
  } catch {
    return null;
  }
}

/** Saves `keys`, or forgets the choice when `keys` is `null` ("Reset to
 *  default"). A failure is swallowed: the link still carries the choice. */
export function writeSavedColumns(typeKey: string, keys: readonly string[] | null): void {
  try {
    if (keys === null) window.localStorage.removeItem(columnStorageKey(typeKey));
    else window.localStorage.setItem(columnStorageKey(typeKey), JSON.stringify(keys));
  } catch {
    // Storage refused (private mode, quota): the URL is still the record.
  }
}
