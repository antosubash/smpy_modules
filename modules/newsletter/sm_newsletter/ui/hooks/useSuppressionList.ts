import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { Suppression, SuppressionPage } from '../utils/types';

/** The API's default page size (`limit` on `GET /suppressions`). */
export const PAGE_SIZE = 50;

/** The suppressed addresses: a reason filter (with the per-reason counts the server
 *  returns) and offset paging. A new reason puts the list back on its first page;
 *  only the newest request may write state. */
export function useSuppressionList() {
  const { t } = useT();
  const [reason, setReasonState] = useState('');
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<Suppression[] | null>(null);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<SuppressionPage['counts']>({});
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const latest = useRef(0);

  // `version` is not read: bumping it is how `reload` re-runs this effect.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const request = ++latest.current;
    const controller = new AbortController();
    void api
      .listSuppressions({ reason: reason || undefined, offset }, controller.signal)
      .then((page) => {
        if (request !== latest.current) return;
        setError(null);
        setItems(page.items);
        setTotal(page.total);
        setCounts(page.counts);
      })
      .catch((e) => {
        if (request !== latest.current || controller.signal.aborted) return;
        setError(errorMessage(e, t));
      });
    return () => controller.abort();
  }, [reason, offset, version, t]);

  const setReason = useCallback((next: string) => {
    setReasonState(next);
    setOffset(0);
  }, []);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return { items, total, counts, reason, setReason, offset, setOffset, error, reload };
}
