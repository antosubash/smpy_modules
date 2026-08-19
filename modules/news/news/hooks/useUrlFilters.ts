import { useCallback, useEffect, useState } from 'react';

export interface NewsFilters {
  category: string;
  /** Free-text search over headline and slug. */
  q: string;
  /** '', 'draft', 'published' or 'undated'. Empty is the All pill. */
  status: string;
  offset: number;
}

const EMPTY: NewsFilters = { category: '', q: '', status: '', offset: 0 };

function fromSearch(search: string): NewsFilters {
  const params = new URLSearchParams(search);
  const offset = Number.parseInt(params.get('offset') ?? '', 10);
  return {
    category: params.get('category') ?? '',
    q: params.get('q') ?? '',
    status: params.get('status') ?? '',
    // A hand-edited or stale "?offset=abc" should land on page one rather than
    // NaN its way into the request.
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

function toSearch({ category, q, status, offset }: NewsFilters): string {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (q) params.set('q', q);
  if (status) params.set('status', status);
  if (offset > 0) params.set('offset', String(offset));
  const query = params.toString();
  return query ? `?${query}` : '';
}

/**
 * Category + paging held in the query string instead of component state.
 *
 * The list fetches its own rows, so there is no Inertia round trip to hang
 * this on — but the reason for doing it is the same one that applies to the
 * page list: a filtered view should survive a reload and be linkable, rather
 * than resetting itself the moment someone refreshes or shares the URL.
 *
 * `replaceState`, not `pushState`: stepping Back through every pill click a
 * user made is not what Back is for, and it would trap them on the page.
 */
export function useUrlFilters(): [NewsFilters, (next: Partial<NewsFilters>) => void] {
  const [filters, setFilters] = useState<NewsFilters>(() =>
    typeof window === 'undefined' ? EMPTY : fromSearch(window.location.search),
  );

  useEffect(() => {
    const url = `${window.location.pathname}${toSearch(filters)}`;
    if (url !== `${window.location.pathname}${window.location.search}`) {
      window.history.replaceState(window.history.state, '', url);
    }
  }, [filters]);

  const update = useCallback((next: Partial<NewsFilters>) => {
    setFilters((prev) => ({ ...prev, ...next }));
  }, []);

  return [filters, update];
}
