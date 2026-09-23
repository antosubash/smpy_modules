import { router } from '@inertiajs/react';
import { useState } from 'react';

import { readSavedColumns, writeSavedColumns } from '../utils/column-storage';
import {
  availableColumns,
  type ListColumn,
  type ListUrlChange,
  type ListUrlState,
  listParams,
  type ResolvedColumns,
  resolveListColumns,
  type SortState,
  sortHiddenBy,
} from '../utils/listing';
import type { TypeRead } from '../utils/types';

/** A search string with its commas left literal — `?columns=a,b` is the form
 *  the docs promise and a person can read. A decoded `%2C` and `,` are the
 *  same character to every query parser, the server's included. */
function readableSearch(params: Record<string, string>): string {
  const search = new URLSearchParams(params).toString().replace(/%2C/gi, ',');
  return search ? `?${search}` : '';
}

/**
 * The record list's column choice: resolved from `?columns=`, else this
 * browser's saved choice for the type, else the default (see
 * `resolveListColumns`), plus the two ways to change it.
 *
 * A change writes both the link and the saved choice. It is a client-side
 * `router.replace` — the server ignores `columns`, so asking it for the same
 * rows again would be a round trip for nothing, and a history entry per
 * tick box would make Back walk through every toggle. The one exception is
 * a change that hides the column the list is sorted by: the sort is then
 * dropped, which does need the server, through the list's usual `goTo`.
 * Either way the URL comes from `listParams`, so a column change keeps the
 * page or cursor the list is on and only a reset drops `columns`.
 */
export function useListColumns({
  type,
  showLocale,
  current,
  currentSort,
  goTo,
}: {
  type: Pick<TypeRead, 'key' | 'fields' | 'display_field'>;
  showLocale: boolean;
  /** The list's URL state, from `useRecordListNav`. */
  current: ListUrlState;
  currentSort: SortState;
  goTo: (next: ListUrlChange) => void;
}) {
  const raw = current.columns ?? null;
  // Keyed by type: the same page component can be handed another type by
  // an Inertia visit that preserves state.
  const [saved, setSaved] = useState(() => ({
    typeKey: type.key,
    keys: readSavedColumns(type.key),
  }));
  const savedKeys = saved.typeKey === type.key ? saved.keys : readSavedColumns(type.key);

  const resolved: ResolvedColumns = resolveListColumns({
    type,
    showLocale,
    raw,
    saved: savedKeys,
  });
  const available: ListColumn[] = availableColumns(type, showLocale);

  const apply = (keys: string[] | null) => {
    writeSavedColumns(type.key, keys);
    setSaved({ typeKey: type.key, keys });
    const param = keys === null ? null : keys.join(',');
    const next = resolveListColumns({ type, showLocale, raw: param, saved: null }).columns;
    if (sortHiddenBy(currentSort, next, available)) {
      goTo({ page: 1, sort: null, columns: param });
      return;
    }
    const params = listParams(current, { columns: param });
    router.replace({
      url: `/admin/records/${type.key}${readableSearch(params)}`,
      preserveScroll: true,
      preserveState: true,
    });
  };

  return {
    resolved,
    available,
    rawColumns: raw,
    /** Show exactly `keys`, in this order. */
    change: (keys: string[]) => apply(keys),
    /** Back to the default rule: the link loses `columns` and the saved
     *  choice is forgotten. */
    reset: () => apply(null),
  };
}
