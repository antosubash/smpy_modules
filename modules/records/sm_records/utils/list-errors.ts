/**
 * What the record list *says*: the sentence for a refused query and the
 * live-region announcement after a navigation. Split out of `listing.ts` for
 * the 300-line cap when the list learned cursor paging; `listing.ts`
 * re-exports every name here, so no import site had to move.
 */

import type { Translate } from './i18n';
import { keys } from './i18n';

/**
 * The `reason` values `record_list` (`endpoints/views.py`, via
 * `endpoints/_list_view.py`) can put in the Inertia `errors` bag as
 * `errors.filter`. The first five are `sm_records.index._predicates.QueryError`'s
 * — see `index/query.py` and `index/_predicates.py` for every call site —
 * raised whether the offending term came from `?filter=` or `?sort=`. The last
 * two are the cursor's: the same refusals the JSON API answers with a 400.
 */
const FILTER_ERROR_REASONS = [
  'reindexing',
  'unsupported_op',
  'not_indexed',
  'unknown',
  'bad_value',
  'bad_cursor',
  'page_and_after',
] as const;

export type FilterErrorReason = (typeof FILTER_ERROR_REASONS)[number] | 'generic';

/**
 * Normalises a `?filter=`/`?sort=`/`?after=` failure's `reason` to a
 * translation-key suffix, falling back to `'generic'` for anything not in the
 * closed set above — a reason this build doesn't recognise (a future server
 * addition this build predates) still needs a message, just not a wrong one
 * for something specific it isn't.
 */
export function filterErrorReasonKey(reason: string | undefined): FilterErrorReason {
  return reason && (FILTER_ERROR_REASONS as readonly string[]).includes(reason)
    ? (reason as FilterErrorReason)
    : 'generic';
}

/** The refusal was about the `?after=` cursor, not the filter or sort. The
 *  list still shows the notice, but "Export" keeps the filter and the empty
 *  box offers the first page rather than clearing a filter that was fine. */
export function isCursorRefusal(reason: string | undefined): boolean {
  const key = filterErrorReasonKey(reason);
  return key === 'bad_cursor' || key === 'page_and_after';
}

/**
 * The sentence for a `?filter=`/`?sort=`/`?after=` term the server refused.
 */
export function filterErrorMessage(t: Translate, reason: string | undefined): string {
  switch (filterErrorReasonKey(reason)) {
    case 'reindexing':
      return t(keys.records.list.filter_error.reindexing);
    case 'unsupported_op':
      return t(keys.records.list.filter_error.unsupported_op);
    case 'not_indexed':
      return t(keys.records.list.filter_error.not_indexed);
    case 'unknown':
      return t(keys.records.list.filter_error.unknown);
    case 'bad_value':
      return t(keys.records.list.filter_error.bad_value);
    case 'bad_cursor':
      return t(keys.records.list.filter_error.bad_cursor);
    case 'page_and_after':
      return t(keys.records.list.filter_error.page_and_after);
    default:
      return t(keys.records.list.filter_error.generic);
  }
}

/** What the visually-hidden live region announces after a filter, a sort or
 *  a page (UX-R15): these navigations swap the table's rows through a
 *  partial Inertia reload with no focus move, so the page silently became a
 *  different page. The page count is dropped when `capped` — past the
 *  ceiling (F4) there is no last page to name — and the page number too on
 *  a page reached by cursor (`page: null`), which has none. An empty cursor
 *  page is the end of the list, not "0 records, continuing". */
export function listStatus(
  t: Translate,
  {
    count,
    page,
    pages,
    capped,
  }: { count: number; page: number | null; pages: number; capped: boolean },
): string {
  if (page === null && count === 0) {
    // Past the last row: nothing continues (review 4, ux F5).
    return t(keys.records.records.list_status_cursor_end);
  }
  if (page === null) {
    return t(keys.records.records.list_status_cursor, {
      count,
    });
  }
  if (capped) {
    return t(keys.records.records.list_status_uncounted, {
      count,
      page,
    });
  }
  return t(keys.records.records.list_status, {
    count,
    page,
    pages,
  });
}
