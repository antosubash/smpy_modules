/**
 * The export menu's scope sentence, split out of `io.ts` for the 300-line
 * cap when it learned about capped counts; `io.ts` re-exports it.
 */

import type { Translate } from './translate';

/**
 * U16: "Download CSV"/"Download JSON" disclosed nothing about *how much* —
 * export honours the list's current filter and the trash toggle (verified:
 * `state:eq:CA` → 4 rows on screen, 4 rows in the file), and an admin
 * exporting for a backup right after filtering got a silent subset. Says
 * the scope in the menu item itself, so the count is read before the click
 * rather than discovered after opening the download.
 *
 * `capped`: the list's `total` is `RecordsSettings.max_count`, not the
 * count (`total_capped`) — while the export writes every matching row. The
 * menu then says "32+", the same number the footer's "of 32+" shows, rather
 * than promising 32 records in a file that holds 59 (review 4, ux F4).
 */
export function exportScopeLabel(
  t: Translate,
  {
    trashed,
    filtered,
    count,
    capped = false,
  }: { trashed: boolean; filtered: boolean; count: number; capped?: boolean },
): string {
  if (capped) {
    const total = `${count.toLocaleString()}+`;
    if (trashed) {
      return t('records.io.scope_trashed_capped', {
        total,
        defaultValue: '{total} trashed records',
      });
    }
    if (filtered) {
      return t('records.io.scope_filtered_capped', {
        total,
        defaultValue: '{total} filtered records',
      });
    }
    return t('records.io.scope_all_capped', { total, defaultValue: 'all {total} records' });
  }
  if (trashed) {
    return t('records.io.scope_trashed', {
      count,
      defaultValue: '{count} trashed record',
      defaultValue_other: '{count} trashed records',
    });
  }
  if (filtered) {
    return t('records.io.scope_filtered', {
      count,
      defaultValue: '{count} filtered record',
      defaultValue_other: '{count} filtered records',
    });
  }
  return t('records.io.scope_all', {
    count,
    defaultValue: 'all {count} records',
  });
}
