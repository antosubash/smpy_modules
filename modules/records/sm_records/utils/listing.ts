/**
 * List-screen helpers that don't belong in a component: which columns a
 * type's schema earns, and the single-key sort state the record list keeps
 * in the URL.
 *
 * See `docs/plans/2026-09-19-records-module-design.md` §7.2 — only indexed
 * fields are queryable, which is why both halves of this file only ever
 * look at `indexed: true` fields plus the server's fixed columns.
 */

import type { FieldDef, FilterOp, TypeRead } from './types';

export const MAX_LIST_COLUMNS = 4;

/**
 * The indexed-field columns rendered after `display_title` on the record
 * list. Capped at four so the table doesn't outgrow a normal viewport, and
 * taken in the type's own field order (not re-sorted) so the columns match
 * the order fields appear in on the schema editor.
 *
 * The type's `display_field` is skipped (UX-R5): the Title column already
 * prints exactly that field's value on every row, so a column for it spends
 * a quarter of the table's horizontal budget repeating the first column —
 * and, since the four-column cap bites before a type's later fields do, it
 * spends it instead of showing a field the user cannot otherwise see.
 */
export function listColumns(
  type: Pick<TypeRead, 'fields'> & Partial<Pick<TypeRead, 'display_field'>>,
): FieldDef[] {
  return type.fields
    .filter((field) => field.indexed && field.key !== type.display_field)
    .slice(0, MAX_LIST_COLUMNS);
}

// ---- Sorting ----------------------------------------------------------

export type SortDir = 'asc' | 'desc';
export type SortState = { field: string; dir: SortDir } | null;

/**
 * The click-cycle for one column header: none → asc → desc → none.
 * Clicking a *different* column always lands on `asc` for it — this UI
 * keeps a single sort key even though the server grammar (`?sort=` repeats)
 * accepts several.
 */
export function nextSort(current: SortState, field: string): SortState {
  if (!current || current.field !== field) return { field, dir: 'asc' };
  if (current.dir === 'asc') return { field, dir: 'desc' };
  return null;
}

/**
 * Parses `?sort=field` / `?sort=-field` out of a location-style search
 * string (`window.location.search`, or the query half of Inertia's page
 * url). The server grammar allows repeats; this UI only ever writes one, so
 * only the first `sort` param is read back.
 */
export function parseSort(search: string): SortState {
  const params = new URLSearchParams(search);
  const raw = params.get('sort');
  if (!raw) return null;
  if (raw.startsWith('-')) return { field: raw.slice(1), dir: 'desc' };
  return { field: raw, dir: 'asc' };
}

/**
 * The inverse of `parseSort` — the value to put in the `sort` query param,
 * or `undefined` when no sort should be applied at all (the caller decides
 * whether "no sort" means omitting the param or clearing it explicitly).
 */
export function buildSortParam(sort: SortState): string | undefined {
  if (!sort) return undefined;
  return sort.dir === 'desc' ? `-${sort.field}` : sort.field;
}

// ---- Filter errors ------------------------------------------------------

/**
 * The `reason` values `sm_records.index._predicates.QueryError` can carry —
 * see `index/query.py` and `index/_predicates.py` for every call site.
 * `record_list` (`endpoints/views.py`) attaches `{filter: exc.reason}` to the
 * Inertia `errors` bag whenever building the query fails, regardless of
 * whether the offending term came from `?filter=` or `?sort=`.
 */
const FILTER_ERROR_REASONS = [
  'reindexing',
  'unsupported_op',
  'not_indexed',
  'unknown',
  'bad_value',
] as const;

export type FilterErrorReason = (typeof FILTER_ERROR_REASONS)[number] | 'generic';

/**
 * Normalises a `?filter=`/`?sort=` failure's `reason` to a translation-key
 * suffix, falling back to `'generic'` for anything not in the closed set
 * above — a reason this build doesn't recognise (a future server addition
 * this build predates) still needs a message, just not a wrong one for
 * something specific it isn't.
 */
export function filterErrorReasonKey(reason: string | undefined): FilterErrorReason {
  return reason && (FILTER_ERROR_REASONS as readonly string[]).includes(reason)
    ? (reason as FilterErrorReason)
    : 'generic';
}

// See `pages/RecordList.tsx` for why `t` is typed this loosely: typing it
// against `useT()`'s real, key-union-overloaded signature either blows up TS
// with an "excessively deep" instantiation or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/**
 * The sentence for a `?filter=`/`?sort=` term the index layer refused.
 *
 * Every branch keeps its own literal `t()` call (rather than a
 * `Record<FilterErrorReason, string>` built once) for the same reason
 * `FilterBar`'s `opLabel` does: an untranslated-string check can read a
 * `t()` call, not a string chosen out of a config object before one.
 *
 * Lives here rather than in `pages/RecordList.tsx` only because that page
 * is up against the 300-line cap.
 */
export function filterErrorMessage(t: Translate, reason: string | undefined): string {
  switch (filterErrorReasonKey(reason)) {
    case 'reindexing':
      return t('records.list.filter_error.reindexing', {
        defaultValue:
          'That field is being reindexed right now and cannot be filtered on yet. Try again shortly.',
      });
    case 'unsupported_op':
      return t('records.list.filter_error.unsupported_op', {
        defaultValue: "That condition isn't supported for this field.",
      });
    case 'not_indexed':
      return t('records.list.filter_error.not_indexed', {
        defaultValue: "That field isn't indexed, so it can't be filtered or sorted on.",
      });
    case 'unknown':
      return t('records.list.filter_error.unknown', {
        defaultValue: "That field doesn't exist on this record type.",
      });
    case 'bad_value':
      return t('records.list.filter_error.bad_value', {
        defaultValue: "That value isn't valid for this field.",
      });
    default:
      return t('records.list.filter_error.generic', {
        defaultValue: "That filter couldn't be applied.",
      });
  }
}

/** What the visually-hidden live region announces after a filter, a sort or
 *  a page (UX-R15): these navigations swap the table's rows through a
 *  partial Inertia reload with no focus move, so the page silently became a
 *  different page. The page count is dropped when `capped` — past the
 *  ceiling (F4) there is no last page to name. */
export function listStatus(
  t: Translate,
  { count, page, pages, capped }: { count: number; page: number; pages: number; capped: boolean },
): string {
  if (capped) {
    return t('records.records.list_status_uncounted', {
      count,
      page,
      defaultValue: '{count} record, page {page}',
      defaultValue_other: '{count} records, page {page}',
    });
  }
  return t('records.records.list_status', {
    count,
    page,
    pages,
    defaultValue: '{count} record, page {page} of {pages}',
    defaultValue_other: '{count} records, page {page} of {pages}',
  });
}

// ---- Trashed toggle -----------------------------------------------------

/** The values pydantic's `bool` query coercion (`deps.py::parse_trashed`'s
 *  `Query(default=False)`) accepts as true, case-insensitively. Anything
 *  else — including an empty string, which pydantic itself rejects with a
 *  422 — reads as false here, the same "not trashed" the server falls back
 *  to for a param it never received at all. */
const TRUE_TRASHED_VALUES = new Set(['1', 'true', 'yes', 'on', 'y', 't']);

/**
 * Whether `?trashed=` should show the trash, matching the server's own
 * `bool` coercion instead of a literal `=== 'true'` (rough edge: `?trashed=1`
 * used to desync the page from what the server actually returned — the
 * server read it as true and served the trash while the page's own
 * `=== 'true'` check read false and rendered the live empty state).
 */
export function parseTrashedParam(raw: string | null): boolean {
  return raw !== null && TRUE_TRASHED_VALUES.has(raw.toLowerCase());
}

/** One filter term as the URL carries it (`?filter=field:op:value`), or
 *  `null` for a list with no filter in force. */
export type FilterValue = { field: string; op: FilterOp; value: string } | null;

/** Split on the first two colons — the value half of `field:op:value` may
 *  itself contain one (an ISO datetime), and the field/op halves never do. */
export function parseFilterParam(raw: string | null): FilterValue {
  if (!raw) return null;
  const first = raw.indexOf(':');
  const second = raw.indexOf(':', first + 1);
  if (first < 0 || second < 0) return null;
  return {
    field: raw.slice(0, first),
    op: raw.slice(first + 1, second) as FilterOp,
    value: raw.slice(second + 1),
  };
}
