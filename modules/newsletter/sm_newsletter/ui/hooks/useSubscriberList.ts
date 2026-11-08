import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { SubscriberPage, SubscriberStatus } from '../utils/types';
import { PAGE_SIZE, SEARCH_DEBOUNCE_MS } from './useCampaignList';

// Every list screen asks for the API's default page (50), as the campaigns do.
export { PAGE_SIZE } from './useCampaignList';

interface Filters {
  listKey: string;
  status: string;
  q: string;
  tag: string;
  segment: string;
  offset: number;
}
type Result = SubscriberPage & { listKey: string };
const initial = (listKey: string): Filters => ({
  listKey,
  status: '',
  q: '',
  tag: '',
  segment: '',
  offset: 0,
});

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
  // Everything that belongs to one list is stored with its key; a state stamped
  // with another list's key reads as the defaults, in the same render, so no
  // request ever carries the previous list's filters.
  const [stored, setStored] = useState<Filters>(() => initial(listKey));
  const [debounced, setDebounced] = useState({ listKey, q: '' });
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const latest = useRef(0);

  const f = stored.listKey === listKey ? stored : initial(listKey);
  const debouncedQ = debounced.listKey === listKey ? debounced.q : '';
  const page = result && result.listKey === listKey ? result : null;
  const { status, q, tag, segment, offset } = f;

  useEffect(() => {
    const timer = setTimeout(() => setDebounced({ listKey, q }), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [listKey, q]);

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
      .then((p) => {
        if (request !== latest.current) return;
        if (offset > 0 && offset >= p.total) {
          // The page emptied under us (its last row was unsubscribed under a status
          // filter): step back to the last page that still has rows.
          const last = Math.max(0, Math.floor((p.total - 1) / PAGE_SIZE) * PAGE_SIZE);
          setStored((cur) => ({
            ...(cur.listKey === listKey ? cur : initial(listKey)),
            offset: last,
          }));
          return;
        }
        setError(null);
        setResult({ listKey, ...p });
      })
      .catch((e) => {
        if (request !== latest.current || controller.signal.aborted) return;
        setError(errorMessage(e, t));
      });
    return () => controller.abort();
  }, [listKey, debouncedQ, status, tag, segment, offset, version, t]);

  const patch = useCallback(
    (change: Partial<Filters>) =>
      setStored((cur) => ({
        ...(cur.listKey === listKey ? cur : initial(listKey)),
        offset: 0,
        ...change,
      })),
    [listKey],
  );
  const setQ = useCallback((next: string) => patch({ q: next }), [patch]);
  const setStatus = useCallback((next: string) => patch({ status: next }), [patch]);
  const setTag = useCallback((next: string) => patch({ tag: next }), [patch]);
  const setSegment = useCallback((next: string) => patch({ segment: next }), [patch]);
  const setOffset = useCallback((next: number) => patch({ offset: next }), [patch]);
  /** Refetch the current page, e.g. after a tag change or an unsubscribe. */
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return {
    items: page?.items ?? null,
    total: page?.total ?? 0,
    counts: page?.counts ?? EMPTY_COUNTS,
    recordsUrl: page?.records_url ?? '',
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
