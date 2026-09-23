import { router } from '@inertiajs/react';
import { useRef, useState } from 'react';

import type { ListUrlChange, ListUrlState, SortState } from '../utils/listing';
import { buildSortParam, listParams, nextSort } from '../utils/listing';
import type { FilterOp } from '../utils/types';

/**
 * Every write `RecordList` makes to the URL — filter, sort, page, cursor,
 * page size, the trash toggle — funnelled through one `goTo()`, plus the U12
 * loading state that request now carries. Split out of the page component
 * for the 300-line cap; `RecordList` itself keeps only what it needs to
 * *render* (the parsed filter/sort/trashed state stays there, since
 * `FilterBar`/`SortableHeader`/the trash button all read it directly).
 */
export function useRecordListNav({
  typeKey,
  page,
  after,
  rawFilter,
  rawSort,
  trashed,
  rawPageSize,
  currentSort,
  rawColumns = null,
}: {
  typeKey: string;
  /** `null` on a page reached by cursor — `records.page`. */
  page: number | null;
  /** `?after=` as the URL carries it: the only place a cursor is ever kept. */
  after: string | null;
  rawFilter: string | null;
  rawSort: string | null;
  trashed: boolean;
  rawPageSize: number;
  currentSort: SortState;
  /** `?columns=` as the URL has it — carried through every navigation so a
   *  filter, sort, page or cursor step never loses the view's chosen
   *  columns. `null` (absent) stays absent: the per-browser default then
   *  applies. */
  rawColumns?: string | null;
}) {
  const listTop = useRef<HTMLDivElement>(null);
  // U12: filter/sort/page/trash-toggle all go through goTo(), and on this
  // local host the round trip is 150-300ms — invisible. At 20k records or
  // over a WAN it wasn't: the previous page's rows stayed on screen with no
  // aria-busy, no spinner and no dimming, asserting stale data while new
  // data was in flight.
  const [loading, setLoading] = useState(false);

  /** After a page change the rows above the fold are replaced silently —
   *  `preserveScroll` keeps the reader pinned to the footer they clicked in
   *  (UX-R18). Put the top of the list back on screen instead. */
  const scrollListIntoView = () => {
    listTop.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  // The URL as it stands. `useListColumns` builds its client-side
  // `?columns=` rewrite from this too, so `listParams` is the only thing
  // that ever writes the list's URL.
  const current: ListUrlState = {
    page: page ?? 1,
    after,
    filter: rawFilter,
    sort: rawSort,
    trashed,
    pageSize: rawPageSize,
    columns: rawColumns,
  };

  const goTo = (next: ListUrlChange) => {
    // `utils/listing.ts::listParams` owns the rules — which change drops the
    // cursor, that `page` and `after` are never written together, and that
    // `columns` survives everything but the chooser's reset.
    const params = listParams(current, next);
    // Toggling `trashed` swaps every prop (`records`, `errors` and, via
    // `parse_trashed`, what the server even lets through) — a partial reload
    // only makes sense for staying inside the same trashed/live view.
    const full = next.trashed !== undefined;
    const paged =
      next.page !== undefined || next.after !== undefined || next.pageSize !== undefined;
    router.get(`/admin/records/${typeKey}`, params, {
      only: full ? undefined : ['records', 'errors'],
      preserveState: true,
      preserveScroll: true,
      // No `replace: true` (UX-R3). Every one of these is a change the user
      // asked for, and collapsing them all into a single history entry meant
      // Back left the list entirely instead of undoing the last filter, sort
      // or page — the universal undo, and the one path `FilterBar`'s
      // remount-on-`key` was written for.
      onSuccess: paged ? scrollListIntoView : undefined,
      onStart: () => setLoading(true),
      onFinish: () => setLoading(false),
    });
  };

  const applyFilter = (field: string, op: FilterOp, value: string) =>
    goTo({ page: 1, filter: `${field}:${op}:${value}` });
  const clearFilter = () => goTo({ page: 1, filter: null });
  const handleSort = (field: string) =>
    goTo({ page: 1, sort: buildSortParam(nextSort(currentSort, field)) ?? null });
  const toggleTrashed = () => goTo({ page: 1, trashed: !trashed });

  return {
    listTop,
    loading,
    current,
    goTo,
    applyFilter,
    clearFilter,
    handleSort,
    toggleTrashed,
  };
}
