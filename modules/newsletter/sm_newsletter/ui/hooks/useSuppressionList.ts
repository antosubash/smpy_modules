import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { Suppression, SuppressionPage } from '../utils/types';
import { PAGE_SIZE } from './useCampaignList';

// Every list screen asks for the API's default page (50), as the campaigns do.
export { PAGE_SIZE } from './useCampaignList';

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
        if (offset > 0 && offset >= page.total) {
          // The page emptied under us (its last row was lifted): step back to the
          // last page that still has rows.
          setOffset(Math.max(0, Math.floor((page.total - 1) / PAGE_SIZE) * PAGE_SIZE));
          return;
        }
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
