import { useCallback, useEffect, useRef, useState } from 'react';

import type { Page } from '../utils/types';

export type CursorList<T> = {
  items: T[];
  total: number | null;
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  loadMore: () => void;
  /** Fetch the first page again, keeping what is shown until it arrives. */
  reload: () => Promise<void>;
};

/**
 * A cursor-paged list that starts over whenever `key` changes.
 *
 * `fetchPage` receives `null` for the first page. A response that arrives after
 * the key changed (or after a newer reload) is dropped, so a slow answer for a
 * previous filter never overwrites the current one. `initial` is the first page
 * for the first key, handed over by the server so the screen renders with data.
 */
export function useCursorList<T>(
  key: string,
  fetchPage: (cursor: string | null) => Promise<Page<T>>,
  initial?: { key: string; page: Page<T> },
): CursorList<T> {
  const seeded = initial && initial.key === key ? initial.page : null;
  const [items, setItems] = useState<T[]>(seeded?.items ?? []);
  const [cursor, setCursor] = useState<string | null>(seeded?.next_cursor ?? null);
  const [total, setTotal] = useState<number | null>(seeded?.total ?? null);
  const [loading, setLoading] = useState(!seeded);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const skipFirst = useRef(Boolean(seeded));

  const first = useCallback(async (keepRows: boolean) => {
    const ticket = ++latest.current;
    if (!keepRows) setLoading(true);
    try {
      const page = await fetchRef.current(null);
      if (ticket !== latest.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      if (ticket === latest.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, []);

  // `key` is the dependency on purpose: it stands for whatever `fetchPage` closes over.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    if (skipFirst.current) {
      skipFirst.current = false;
      return;
    }
    void first(false);
  }, [key, first]);

  const loadMore = useCallback(() => {
    if (!cursor || loading) return;
    const ticket = latest.current;
    setLoading(true);
    fetchRef
      .current(cursor)
      .then((page) => {
        if (ticket !== latest.current) return;
        setItems((rows) => [...rows, ...page.items]);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((e) => {
        if (ticket === latest.current) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false);
      });
  }, [cursor, loading]);

  const reload = useCallback(() => first(true), [first]);

  return { items, total, hasMore: cursor !== null, loading, error, loadMore, reload };
}
