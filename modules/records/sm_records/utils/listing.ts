/**
 * List-screen helpers that don't belong in a component: the single-key sort
 * state the record list keeps in the URL, and the URL itself (`listParams`).
 *
 * Which columns the list shows lives in `list-columns.ts`, and what the list
 * *says* in `list-errors.ts`; both are re-exported here, so every import
 * site can keep importing from `listing`.
 */

import type { FilterOp } from './types';

export {
  availableColumns,
  type ColumnSource,
  defaultColumnKeys,
  ENVELOPE_COLUMNS,
  type EnvelopeColumnKey,
  firstMediaField,
  type ListColumn,
  listColumns,
  MAX_CHOSEN_COLUMNS,
  MAX_LIST_COLUMNS,
  type ResolvedColumns,
  resolveListColumns,
  sortHiddenBy,
} from './list-columns';
export {
  type FilterErrorReason,
  filterErrorMessage,
  filterErrorReasonKey,
  isCursorRefusal,
  listStatus,
} from './list-errors';

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

// ---- The URL ------------------------------------------------------------

/** The page sizes the footer offers. The first is the module's own default
 *  (`RecordsSettings.default_page_size`), which is also what the URL leaves
 *  out: a URL that carries only what differs from the default is the one
 *  worth sharing, and the server clamps whatever does arrive. */
export const PAGE_SIZES = [25, 50, 100] as const;

/** Every param `record_list` (`endpoints/views.py`) reads — the list's whole
 *  state, since the URL *is* the state. `page` is `1` on a cursor page.
 *  `filter` and `sort` are every term the URL carries, in its order: the
 *  grammar repeats both (`?filter=a&filter=b` is ANDed), so a link built
 *  outside this UI can hold several, and a URL rebuilt from only the first
 *  would silently widen the query the screen was rendered for.
 *  `columns` is the one client-only param (`resolveListColumns`): the server
 *  ignores it, absent means the link names no columns, `''` is Title only. */
export type ListUrlState = {
  page: number;
  after: string | null;
  filter: readonly string[];
  sort: readonly string[];
  trashed: boolean;
  pageSize: number;
  columns?: string | null;
};

/** One navigation: only what it changes. `filter`/`sort` replace *every*
 *  term with the one given (the filter bar and a header click each write a
 *  single term), `null` clears them; `columns` takes `null` to clear; `after`
 *  is a `next_cursor` to continue from. */
export type ListUrlChange = Partial<Omit<ListUrlState, 'after' | 'filter' | 'sort' | 'columns'>> & {
  after?: string;
  filter?: string | null;
  sort?: string | null;
  columns?: string | null;
};

/** The terms after a change: untouched ones kept as they were, all of them. */
function terms(current: readonly string[], next: string | null | undefined): readonly string[] {
  if (next === undefined) return current;
  return next ? [next] : [];
}

/**
 * The query params for the list after `next` is applied to `current`.
 *
 * **Paging.** `?page=` and `?after=` are never both written: the server
 * refuses the pair (`page_and_after`), exactly as the API does. A cursor is
 * "the rows after this one *in this order*", so a change of filter, sort,
 * trash view or page size drops it and lands on page 1 — the cursor would
 * either be refused (another sort, the trash) or resume a list the reader is
 * no longer looking at. A numbered page drops it too. Nothing but the URL
 * ever holds the cursor, which is what makes a cursor page shareable and
 * lets Back walk through the pages it came from.
 *
 * **Repeated terms.** Every `filter`/`sort` term a change does not name is
 * written back, in order — a page, a cursor step or a column change never
 * narrows the query to its first term. A `URLSearchParams`, because a plain
 * object cannot hold a key twice; `listSearch` turns it into the URL.
 *
 * **Columns.** `?columns=` is a display choice, not a query: every change
 * keeps it — a page, a cursor step, a filter, sort, trash or page-size
 * change — and only an explicit `columns: null` (the chooser's reset) drops
 * it. Changing it alone reorders nothing, so it keeps the page or cursor.
 */
export function listParams(current: ListUrlState, next: ListUrlChange): URLSearchParams {
  const reordered =
    next.filter !== undefined ||
    next.sort !== undefined ||
    next.trashed !== undefined ||
    next.pageSize !== undefined;
  const params = new URLSearchParams();
  const after = next.after ?? (next.page !== undefined || reordered ? null : current.after);
  const page = next.page ?? (reordered ? 1 : current.page);
  if (after) params.set('after', after);
  else if (page > 1) params.set('page', String(page));
  for (const term of terms(current.filter, next.filter)) if (term) params.append('filter', term);
  for (const term of terms(current.sort, next.sort)) if (term) params.append('sort', term);
  if (next.trashed ?? current.trashed) params.set('trashed', 'true');
  const size = next.pageSize ?? current.pageSize;
  if (size && size !== PAGE_SIZES[0]) params.set('page_size', String(size));
  const columns = next.columns === undefined ? current.columns : next.columns;
  if (typeof columns === 'string') params.set('columns', columns);
  return params;
}

/** `listParams` as the list's URL search, `''` when empty — with its commas
 *  left literal: `?columns=a,b` is the form the docs promise and a person can
 *  read, and a decoded `%2C` and `,` are the same character to every query
 *  parser, the server's included (a literal `%2C` a user typed encodes as
 *  `%252C`, so nothing is corrupted). */
export function listSearch(params: URLSearchParams): string {
  const search = params.toString().replace(/%2C/gi, ',');
  return search ? `?${search}` : '';
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

/**
 * What "Export" should send, given the list's own query string.
 *
 * "Export" means "export what I am looking at", so the screen's
 * `filter`/`sort`/`trashed` travel with the download. The one exception is
 * a filter the server has already refused (`errors.filter` on the page):
 * carrying it makes the export the same refusal, as a raw JSON 400 in a new
 * tab with nothing around it to explain (polish note). Everything else the
 * screen is showing still goes — the paging params `page` and `after` are
 * `exportUrl`'s to drop (`utils/io.ts`).
 */
export function exportSearchParams(search: string, filterFailed: boolean): string {
  if (!filterFailed) return search;
  const params = new URLSearchParams(search);
  params.delete('filter');
  return params.toString();
}
