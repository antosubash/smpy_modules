import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { CampaignSummary } from '../utils/types';

/** The API's default page size (`limit` on `GET /campaigns`). */
export const PAGE_SIZE = 50;

/** How long the search box waits before asking the server: one request per
 *  word rather than one per keystroke. */
export const SEARCH_DEBOUNCE_MS = 250;

/** The campaign list: search, status filter and offset paging.
 *
 *  Any change to the search or the status puts the list back on its first
 *  page, immediately, while the request for a new search term waits for the
 *  debounce. Only the newest request may write state.
 */
export function useCampaignList() {
  const { t } = useT();
  const [q, setQState] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [status, setStatusState] = useState('');
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<CampaignSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [q]);

  // `version` is not read: bumping it is how `reload` re-runs this effect.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const request = ++latest.current;
    const controller = new AbortController();
    void api
      .listCampaigns(
        { q: debouncedQ || undefined, status: status || undefined, offset },
        controller.signal,
      )
      .then((page) => {
        if (request !== latest.current) return;
        if (offset > 0 && offset >= page.total) {
          // The page emptied under us (its last row was deleted): step back
          // to the last page that still has rows.
          setOffset(Math.max(0, Math.floor((page.total - 1) / PAGE_SIZE) * PAGE_SIZE));
          return;
        }
        setError(null);
        setItems(page.items);
        setTotal(page.total);
      })
      .catch((e) => {
        if (request !== latest.current || controller.signal.aborted) return;
        setError(errorMessage(e, t));
      });
    return () => controller.abort();
  }, [debouncedQ, status, offset, version, t]);

  const setQ = useCallback((next: string) => {
    setQState(next);
    setOffset(0);
  }, []);
  const setStatus = useCallback((next: string) => {
    setStatusState(next);
    setOffset(0);
  }, []);
  const nextPage = useCallback(() => setOffset((o) => o + PAGE_SIZE), []);
  const previousPage = useCallback(() => setOffset((o) => Math.max(0, o - PAGE_SIZE)), []);
  /** Refetch the current page, e.g. after a delete. */
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return {
    q,
    status,
    offset,
    items,
    total,
    error,
    pageSize: PAGE_SIZE,
    hasNext: offset + PAGE_SIZE < total,
    filtered: q !== '' || status !== '',
    setQ,
    setStatus,
    nextPage,
    previousPage,
    reload,
  };
}
