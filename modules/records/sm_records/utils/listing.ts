/**
 * List-screen helpers that don't belong in a component: which columns a
 * type's schema earns, and the single-key sort state the record list keeps
 * in the URL.
 *
 * See `docs/plans/2026-09-19-records-module-design.md` §7.2 — only indexed
 * fields are queryable, which is why both halves of this file only ever
 * look at `indexed: true` fields plus the server's fixed columns.
 */

import type { FieldDef, TypeRead } from './types';

export const MAX_LIST_COLUMNS = 4;

/**
 * The indexed-field columns rendered after `display_title` on the record
 * list. Capped at four so the table doesn't outgrow a normal viewport, and
 * taken in the type's own field order (not re-sorted) so the columns match
 * the order fields appear in on the schema editor.
 */
export function listColumns(type: Pick<TypeRead, 'fields'>): FieldDef[] {
  return type.fields.filter((field) => field.indexed).slice(0, MAX_LIST_COLUMNS);
}

// ---- Sorting ----------------------------------------------------------

export type SortDir = 'asc' | 'desc';
export type SortState = { field: string; dir: SortDir } | null;

/**
 * The list's fixed sortable columns — `sm_records.index.query.FIXED_COLUMNS`
 * minus `slug`/`created_at`, which this screen doesn't give a header to.
 * Kept as a plain literal here rather than imported: this is TS reaching for
 * a constant that lives in a Python module, and the two sides are kept in
 * sync by hand (and by `record_list`'s 400/409 handling being exercised by
 * only ever emitting one of these, or an indexed field, as `?sort=`).
 */
export const FIXED_SORT_COLUMNS = [
  'display_title',
  'status',
  'updated_at',
  'published_at',
  'position',
] as const;

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
