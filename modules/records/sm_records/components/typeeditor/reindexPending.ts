/**
 * Turning `TypeRead.reindex_pending` (a bare `{ field_key | "*": iso_since }`
 * map, §8.5/§8.9) into an ordered, display-ready list. Pure so
 * `reindexPending.test.ts` can pin the "whole type" sentinel and the sort
 * order without mounting `ReindexStatus`.
 */

export type ReindexPendingEntry = {
  key: string;
  since: string;
  /** `key === "*"` — the design's sentinel for "the whole type", not one
   *  field (§8.5: `reindex_pending` is a list on the type, not a per-field
   *  flag inside `fields`). */
  wholeType: boolean;
};

/** Whole-type entries first (there is at most one), then field keys in
 *  alphabetical order — so the list doesn't reshuffle on every poll just
 *  because object key order isn't guaranteed to be stable across responses. */
export function pendingEntries(pending: Record<string, string>): ReindexPendingEntry[] {
  return Object.entries(pending)
    .map(([key, since]) => ({ key, since, wholeType: key === '*' }))
    .sort((a, b) => {
      if (a.wholeType !== b.wholeType) return a.wholeType ? -1 : 1;
      return a.key.localeCompare(b.key);
    });
}
