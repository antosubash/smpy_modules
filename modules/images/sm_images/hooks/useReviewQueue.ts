import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../utils/api';
import {
  listReview,
  type ReviewAction,
  type ReviewFilter,
  type ReviewItem,
  reviewResult,
} from '../utils/api-review';

export type ReviewOutcome = { outcome: 'saved' | 'stale' | 'failed'; message?: string };

export type ReviewQueue = {
  items: ReviewItem[] | null;
  error: string | null;
  hasMore: boolean;
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

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** A collection's review queue for one status and prompt, paged by cursor. */
export function useReviewQueue(
  collectionId: string,
  status: ReviewFilter,
  prompt: string | null,
): ReviewQueue {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const page = await listReview(collectionId, { status, prompt });
      if (ticket !== latest.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
      setError(null);
    } catch (e) {
      if (ticket === latest.current) setError(message(e));
    }
  }, [collectionId, status, prompt]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const loadMore = useCallback(() => {
    if (cursor === null) return;
    const ticket = latest.current;
    listReview(collectionId, { status, prompt, after: cursor })
      .then((page) => {
        if (ticket !== latest.current) return;
        setItems((before) => [...(before ?? []), ...page.items]);
        setCursor(page.next_cursor);
      })
      .catch((e) => setError(message(e)));
  }, [collectionId, status, prompt, cursor]);

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
        return { outcome: 'failed' as const, message: message(e) };
      } finally {
        setBusy(false);
      }
    },
    [status, reload],
  );

  return { items, error, hasMore: cursor !== null, busy, loadMore, reload, review };
}
