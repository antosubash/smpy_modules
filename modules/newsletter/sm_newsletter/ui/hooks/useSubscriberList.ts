import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { Subscriber, SubscriberPage, SubscriberStatus } from '../utils/types';
import { SEARCH_DEBOUNCE_MS } from './useCampaignList';

/** The API's default page size (`limit` on `POST …/subscribers/search`). */
export const PAGE_SIZE = 50;

const EMPTY_COUNTS: SubscriberPage['counts'] = { pending: 0, confirmed: 0, unsubscribed: 0 };

/** One list's subscribers: status, search, tag and segment filters, offset paging.
 *
 *  The search text lives in this hook's state only and travels in the POST body
 *  (C5): never a query string, a route or a history entry. Any filter change puts
 *  the list back on its first page, the search request waits for the debounce,
 *  and only the newest response may write state.
 */
export function useSubscriberList(listKey: string) {
  const { t } = useT();
  const [status, setStatusState] = useState('');
  const [q, setQState] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [tag, setTagState] = useState('');
  const [segment, setSegmentState] = useState('');
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<Subscriber[] | null>(null);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<SubscriberPage['counts']>(EMPTY_COUNTS);
  const [recordsUrl, setRecordsUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [q]);

  // A different list starts from scratch.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on listKey only
  useEffect(() => {
    setStatusState('');
    setQState('');
    setDebouncedQ('');
    setTagState('');
    setSegmentState('');
    setOffset(0);
    setItems(null);
  }, [listKey]);

  // `version` is not read: bumping it is how `reload` re-runs this effect.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    if (!listKey) return;
    const request = ++latest.current;
    const controller = new AbortController();
    void api
      .searchSubscribers(
        listKey,
        {
          status: (status || null) as SubscriberStatus | null,
          q: debouncedQ || null,
          tag: tag || null,
          segment: segment ? Number(segment) : null,
          offset,
        },
        controller.signal,
      )
      .then((page) => {
        if (request !== latest.current) return;
        setError(null);
        setItems(page.items);
        setTotal(page.total);
        setCounts(page.counts);
        setRecordsUrl(page.records_url);
      })
      .catch((e) => {
        if (request !== latest.current || controller.signal.aborted) return;
        setError(errorMessage(e, t));
      });
    return () => controller.abort();
  }, [listKey, debouncedQ, status, tag, segment, offset, version, t]);

  const setQ = useCallback((next: string) => {
    setQState(next);
    setOffset(0);
  }, []);
  const setStatus = useCallback((next: string) => {
    setStatusState(next);
    setOffset(0);
  }, []);
  const setTag = useCallback((next: string) => {
    setTagState(next);
    setOffset(0);
  }, []);
  const setSegment = useCallback((next: string) => {
    setSegmentState(next);
    setOffset(0);
  }, []);
  /** Refetch the current page, e.g. after a tag change or an unsubscribe. */
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return {
    items,
    total,
    counts,
    recordsUrl,
    status,
    setStatus,
    q,
    setQ,
    tag,
    setTag,
    segment,
    setSegment,
    offset,
    setOffset,
    error,
    reload,
  };
}
