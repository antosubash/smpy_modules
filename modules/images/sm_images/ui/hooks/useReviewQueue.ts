import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../utils/api';
import { errorText } from '../utils/api-net';
import {
  listReview,
  type ReviewAction,
  type ReviewFilter,
  type ReviewItem,
  reviewResult,
} from '../utils/api-review';

export type ReviewOutcome = { outcome: 'saved' | 'stale' | 'failed'; message?: string };

/** The queue is topped up from the next page when fewer than this are left. */
export const REFILL_BELOW = 10;

export type ReviewQueue = {
  items: ReviewItem[] | null;
  error: string | null;
  hasMore: boolean;
  /** A page is being read: an empty list is not final yet. */
  loading: boolean;
  busy: boolean;
  loadMore: () => void;
  reload: () => Promise<void>;
  /** Review `item`. `saved` removes it from an `unreviewed` queue (else
   *  replaces it); `stale` reloads - the result changed under the reviewer. */
  review: (
    item: ReviewItem,
    action: ReviewAction,
    data?: Record<string, unknown>,
  ) => Promise<ReviewOutcome>;
};

/** `more` after `before`, each id once (a page can overlap a reload). */
function append(before: ReviewItem[], more: ReviewItem[]): ReviewItem[] {
  const seen = new Set(before.map((i) => i.id));
  return [...before, ...more.filter((i) => !seen.has(i.id))];
}

/**
 * A collection's review queue for one status and prompt, paged by cursor.
 * One page is read at a time, and the next is read by itself when reviewing
 * has left fewer than :data:`REFILL_BELOW`, so the queue is never empty while
 * the server still holds more.
 */
export function useReviewQueue(
  collectionId: string,
  status: ReviewFilter,
  prompt: string | null,
): ReviewQueue {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  // The filter whose first page is on screen. A cursor belongs to it alone, so
  // nothing pages until it is the current one (a filter change in between
  // would send the old cursor with the new filter and skip rows).
  const [loaded, setLoaded] = useState<string | null>(null);
  const filter = `${collectionId}|${status}|${prompt ?? ''}`;
  const latest = useRef(0);
  const paging = useRef(0); // the ticket a page read is running under, else 0

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    setLoaded(null);
    setCursor(null);
    try {
      const page = await listReview(collectionId, { status, prompt });
      if (ticket !== latest.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
      setLoaded(filter);
      setError(null);
    } catch (e) {
      if (ticket === latest.current) setError(errorText(e));
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [collectionId, status, prompt, filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const loadMore = useCallback(() => {
    if (cursor === null || loaded !== filter || paging.current === latest.current) return;
    const ticket = latest.current;
    paging.current = ticket;
    setLoading(true);
    listReview(collectionId, { status, prompt, after: cursor })
      .then((page) => {
        if (ticket !== latest.current) return;
        setItems((before) => append(before ?? [], page.items));
        setCursor(page.next_cursor);
      })
      .catch((e) => {
        if (ticket === latest.current) setError(errorText(e));
      })
      .finally(() => {
        if (paging.current === ticket) paging.current = 0;
        if (ticket === latest.current) setLoading(false);
      });
  }, [collectionId, status, prompt, cursor, loaded, filter]);

  const remaining = items?.length ?? null;
  useEffect(() => {
    if (remaining !== null && remaining < REFILL_BELOW && cursor !== null && !error) loadMore();
  }, [remaining, cursor, error, loadMore]);

  const review = useCallback(
    async (item: ReviewItem, action: ReviewAction, data?: Record<string, unknown>) => {
      setBusy(true);
      try {
        const done = await reviewResult(item.id, action, item.version, data);
        setItems((all) =>
          (all ?? []).flatMap((i) =>
            i.id !== item.id ? [i] : status === 'unreviewed' ? [] : [done],
          ),
        );
        return { outcome: 'saved' as const };
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          await reload();
          return { outcome: 'stale' as const };
        }
        return { outcome: 'failed' as const, message: errorText(e) };
      } finally {
        setBusy(false);
      }
    },
    [status, reload],
  );

  return {
    items,
    error,
    hasMore: cursor !== null,
    loading,
    busy,
    loadMore,
    reload,
    review,
  };
}
