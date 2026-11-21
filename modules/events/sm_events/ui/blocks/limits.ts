/** Mirrors `UPCOMING_BLOCK_*` and `BLOCK_CALENDARS_MAX` in `sm_events/core/constants/public.py`
 *  (`limits.test.ts` reads them). The server enforces them; these keep a stored value that
 *  predates a bound, or a number field's fraction, from becoming a 422 that blanks the block. */
export const UPCOMING_MIN = 1;
export const UPCOMING_MAX = 20;
export const UPCOMING_DEFAULT = 5;
export const CALENDARS_MAX = 10;

/** A count in `[UPCOMING_MIN, UPCOMING_MAX]`, whole; anything else is the default. */
export function clampCount(value: unknown): number {
  const n = Math.trunc(Number(value));
  if (!Number.isFinite(n)) return UPCOMING_DEFAULT;
  return Math.min(UPCOMING_MAX, Math.max(UPCOMING_MIN, n));
}

/** `value` when it is one of `allowed`, else `fallback` (stored props are editor input). */
export function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** The slugs of a block's `calendars` array: strings only, no blanks or repeats, at most
 *  `CALENDARS_MAX`. Whatever else a stored value held is dropped. */
export function slugsOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const slugs = value
    .map((row) => (row && typeof row === 'object' ? (row as { slug?: unknown }).slug : undefined))
    .filter((slug): slug is string => typeof slug === 'string' && slug.trim() !== '')
    .map((slug) => slug.trim());
  return [...new Set(slugs)].slice(0, CALENDARS_MAX);
}

/** What a block's `calendars` prop says. Only an absent or empty selection (or one of blank rows,
 *  the picker's "All public calendars") means every public calendar. Anything that cannot be read
 *  as `[{ slug }]` (a string, a number, an entry that is null or has no string `slug`) or that
 *  names more than the cap is `bad`: the block then shows nothing, never every calendar. */
export function selectionOf(value: unknown): { slugs: string[]; bad: boolean } {
  if (value === undefined || value === null) return { slugs: [], bad: false };
  if (!Array.isArray(value)) return { slugs: [], bad: true };
  const slugs: string[] = [];
  for (const row of value) {
    if (!row || typeof row !== 'object' || typeof (row as { slug?: unknown }).slug !== 'string') {
      return { slugs: [], bad: true };
    }
    const slug = ((row as { slug: string }).slug ?? '').trim();
    if (slug !== '' && !slugs.includes(slug)) slugs.push(slug);
  }
  return { slugs, bad: slugs.length > CALENDARS_MAX };
}

/** Why a count is refused: not a whole number, or outside the range. `null` when it is fine. */
export function countProblem(value: unknown): 'integer' | 'range' | null {
  if (typeof value !== 'number' || !Number.isInteger(value)) return 'integer';
  return value < UPCOMING_MIN || value > UPCOMING_MAX ? 'range' : null;
}
