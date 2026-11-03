import { useCallback, useEffect, useState } from 'react';

export interface NewsFilters {
  category: string;
  /** Free-text search over headline and slug. */
  q: string;
  /** '', 'draft', 'published' or 'undated'. Empty is the All pill. */
  status: string;
  /** Language tag, or '' for every language — the list's default. An editor
   *  looking for an article should not have to guess which translation of it
   *  they filed the headline under. */
  locale: string;
  offset: number;
}

const EMPTY: NewsFilters = { category: '', q: '', status: '', locale: '', offset: 0 };

function fromSearch(search: string): NewsFilters {
  const params = new URLSearchParams(search);
  const offset = Number.parseInt(params.get('offset') ?? '', 10);
  return {
    category: params.get('category') ?? '',
    q: params.get('q') ?? '',
    status: params.get('status') ?? '',
    locale: params.get('locale') ?? '',
    // A hand-edited or stale "?offset=abc" should land on page one rather than
    // NaN its way into the request.
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

function toSearch({ category, q, status, locale, offset }: NewsFilters, current: string): string {
  // Start from the current query string, not a fresh one: this hook owns only
  // its own keys, and rebuilding from scratch would silently strip params
  // other features (or analytics links) put there.
  const params = new URLSearchParams(current);
  if (category) params.set('category', category);
  else params.delete('category');
  if (q) params.set('q', q);
  else params.delete('q');
  if (status) params.set('status', status);
  else params.delete('status');
  if (locale) params.set('locale', locale);
  else params.delete('locale');
  if (offset > 0) params.set('offset', String(offset));
  else params.delete('offset');
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
    const url = `${window.location.pathname}${toSearch(filters, window.location.search)}`;
    if (url !== `${window.location.pathname}${window.location.search}`) {
      window.history.replaceState(window.history.state, '', url);
    }
  }, [filters]);

  const update = useCallback((next: Partial<NewsFilters>) => {
    setFilters((prev) => ({ ...prev, ...next }));
  }, []);

  return [filters, update];
}
