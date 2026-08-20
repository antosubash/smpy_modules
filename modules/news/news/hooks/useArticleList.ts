import { useCallback, useEffect, useRef, useState } from 'react';

import {
  type ArticleCounts,
  type ArticleRead,
  type CategoryCount,
  listArticles,
  listCategories,
} from '../utils/api';
import { useUrlFilters } from './useUrlFilters';

export const PAGE_SIZE = 20;

/** How long the search box waits before asking the server.
 *
 * Long enough that typing a word is one request rather than five, short enough
 * that the list still feels attached to the keyboard.
 */
const SEARCH_DEBOUNCE_MS = 250;

const EMPTY_COUNTS: ArticleCounts = { all: 0, draft: 0, published: 0, undated: 0 };

/** Loads the article list, its filters and its counts.
 *
 * Paging is "load more" rather than pages, so `offset` is how much has been
 * *accumulated* rather than where a window starts. Any filter change resets it
 * to zero and replaces the list; only `loadMore` appends.
 */
export function useArticleList() {
  const [articles, setArticles] = useState<ArticleRead[] | null>(null);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [counts, setCounts] = useState<ArticleCounts>(EMPTY_COUNTS);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useUrlFilters();

  // Debounced copy of the search term. The input stays fully controlled by
  // `filters.q` so typing never lags; only the request waits.
  const [debouncedQ, setDebouncedQ] = useState(filters.q);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(filters.q), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [filters.q]);

  // Only the newest request may write state. An AbortSignal alone does not
  // cover this: `runRow` refreshes without one, so a save's re-fetch could
  // still land after a filter change and paint the old filter's rows under the
  // new pills, with nothing left to re-fetch and correct it.
  const latest = useRef(0);

  const fetchPage = useCallback(
    async (offset: number, append: boolean, signal?: AbortSignal) => {
      const request = ++latest.current;
      const superseded = () => request !== latest.current;

      const rows = listArticles({
        limit: PAGE_SIZE,
        offset,
        category: filters.category || undefined,
        q: debouncedQ || undefined,
        status: filters.status || undefined,
        // Undated first: an undated article is work in progress — with the
        // default (public-feed) order it would sit on the last page, burying
        // exactly the row its author just created.
        undated_first: true,
        signal,
      })
        .then((response) => {
          if (superseded()) return;
          // A load that worked clears a banner left by one that did not.
          setError(null);
          setArticles((current) =>
            append && current ? [...current, ...response.items] : response.items,
          );
          setTotal(response.total);
          setCounts(response.counts ?? EMPTY_COUNTS);
        })
        .catch((e) => {
          if (superseded() || signal?.aborted) return;
          setError((e as Error).message);
        });

      // Pills and suggestions only — a failure here just means no category
      // select, which is not worth an error banner over a usable list.
      const cats = listCategories(signal)
        .then((response) => {
          if (superseded()) return;
          setCategories(response.items);
        })
        .catch(() => {
          // Deliberately keep the last known list: emptying it unmounts the
          // select, which would strand an active filter with no control left
          // to clear it.
        });

      await Promise.all([rows, cats]);
    },
    [filters.category, filters.status, debouncedQ],
  );

  /** Reload from the top. Called on mount and whenever a filter changes. */
  const load = useCallback(
    async (signal?: AbortSignal) => {
      await fetchPage(0, false, signal);
    },
    [fetchPage],
  );

  const loadMore = useCallback(() => {
    setBusy(true);
    void fetchPage(articles?.length ?? 0, true).finally(() => setBusy(false));
  }, [fetchPage, articles?.length]);

  // Busy is per row, so saving one article does not lock every other row's
  // inputs while the request is in flight.
  const runRow = useCallback(
    async (id: number, work: () => Promise<unknown>) => {
      setBusyId(id);
      setError(null);
      try {
        await work();
        // Awaited: clearing busy before the new rows land re-enables a row
        // that is about to disappear, and a second action on it answers 404.
        await fetchPage(0, false);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusyId(null);
      }
    },
    [fetchPage],
  );

  return {
    articles,
    categories,
    counts,
    total,
    shown: articles?.length ?? 0,
    busy,
    busyId,
    error,
    filters,
    setFilters,
    load,
    loadMore,
    runRow,
  };
}
