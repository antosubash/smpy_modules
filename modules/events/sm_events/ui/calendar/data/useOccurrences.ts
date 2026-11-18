/** The occurrences for the visible range: one abortable request per navigation that leaves
 *  the cached range, answers for an older range dropped, and the page kept for the next
 *  navigation inside it. */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { SourceStatus } from '../../extensions/types';
import { useRequestScope } from '../../hooks/useRequestScope';
import type { Occurrence } from '../../utils/types-events';
import { paddedRange, type Range } from '../time/range';
import type { FilterQuery, OccurrenceFetcher } from '../types';
import { filtersKey, RangeCache } from './cache';

type Args = {
  fetcher: OccurrenceFetcher;
  visible: Range | null;
  filters: FilterQuery;
  refreshToken: number;
};
type State = {
  items: Occurrence[];
  truncated: boolean;
  sources: SourceStatus[];
  loading: boolean;
  error: unknown | null;
};
const EMPTY: State = { items: [], truncated: false, sources: [], loading: false, error: null };

export function useOccurrences({ fetcher, visible, filters, refreshToken }: Args) {
  const begin = useRequestScope(true);
  const cache = useRef(new RangeCache()).current;
  const inFlight = useRef<AbortController | null>(null);
  const latest = useRef({ fetcher, filters });
  latest.current = { fetcher, filters };
  const lastToken = useRef(refreshToken);
  const [state, setState] = useState<State>(EMPTY);
  const [nonce, setNonce] = useState(0);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  const invalidate = useCallback(() => {
    cache.clear();
    setNonce((n) => n + 1);
  }, [cache]);

  useEffect(() => () => inFlight.current?.abort(), []);

  const key = filtersKey(filters);
  const start = visible?.start;
  const end = visible?.end;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `nonce` re-runs it for retry and invalidate
  useEffect(() => {
    if (lastToken.current !== refreshToken) {
      lastToken.current = refreshToken;
      cache.clear();
    }
    inFlight.current?.abort();
    inFlight.current = null;
    if (start === undefined || end === undefined) {
      setState((now) => ({ ...now, loading: false }));
      return;
    }
    const range = { start, end };
    const hit = cache.find(range, key);
    if (hit) {
      setState({
        items: hit.items,
        truncated: hit.truncated,
        sources: hit.sources ?? [],
        loading: false,
        error: null,
      });
      return;
    }
    const mine = new AbortController();
    inFlight.current = mine;
    const scoped = begin();
    scoped.signal.addEventListener('abort', () => mine.abort());
    const live = () => scoped.alive() && inFlight.current === mine && !mine.signal.aborted;
    const padded = paddedRange(range);
    setState((now) => ({ ...now, loading: true, error: null }));
    latest.current
      .fetcher({ ...latest.current.filters, ...padded }, mine.signal)
      .then((page) => {
        if (!live()) return;
        // A 200 that is not an occurrence page is a failure, not an empty range.
        if (!Array.isArray(page?.items)) throw new TypeError('malformed occurrence page');
        cache.put(padded, key, page);
        setState({
          items: page.items,
          truncated: page.truncated,
          sources: page.sources ?? [],
          loading: false,
          error: null,
        });
      })
      .catch((error: unknown) => {
        if (!live()) return;
        setState((now) => ({ ...now, loading: false, error }));
      });
  }, [start, end, key, refreshToken, nonce, cache, begin]);

  return { ...state, retry, invalidate };
}
