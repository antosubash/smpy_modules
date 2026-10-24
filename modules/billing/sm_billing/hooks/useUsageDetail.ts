import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ADMIN_API, api } from '../utils/api';
import type { Paged, UsageEvent, UsageHold } from '../utils/types';

export const USAGE_API = `${ADMIN_API}/usage`;
const LEDGER_PER_PAGE = 20;

interface Loaded {
  key: string;
  ledger: Paged<UsageEvent>;
  holds: UsageHold[];
}

/**
 * One organisation's ledger page and open holds, for the usage drawer.
 *
 * Fetched when the drawer opens and again whenever a filter, the page or
 * `refresh()` changes; a response for a query the drawer has since left is
 * dropped. `ledger`/`holds` are `null` until the current query has answered,
 * and stay `null` (with `failed`) when it fails. `null` tenant: nothing loads.
 */
export function useUsageDetail(tenantId: string | null, csrf: string, initialMeter = '') {
  const [meter, setMeterState] = useState(initialMeter);
  const [kind, setKindState] = useState('');
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [failedKey, setFailedKey] = useState<string | null>(null);
  // What the controls ask for. Results are shown only while they answer this
  // exact query, so a filter change never leaves the last filter's holds
  // (and their Release buttons) on screen under the new controls.
  const key = JSON.stringify([tenantId, meter, kind, page]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: start over when the drawer opens on another tenant
  useEffect(() => {
    setMeterState(initialMeter);
    setKindState('');
    setPage(1);
  }, [tenantId, initialMeter]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `version` is the refresh trigger
  useEffect(() => {
    if (!tenantId) return;
    let live = true;
    const base = `${USAGE_API}/${encodeURIComponent(tenantId)}`;
    const ledgerQuery = new URLSearchParams({
      page: String(page),
      per_page: String(LEDGER_PER_PAGE),
    });
    const holdsQuery = new URLSearchParams();
    if (meter) {
      ledgerQuery.set('meter', meter);
      holdsQuery.set('meter', meter);
    }
    if (kind) ledgerQuery.set('kind', kind);
    Promise.all([
      api<Paged<UsageEvent>>(`${base}/events?${ledgerQuery}`, csrf),
      api<UsageHold[]>(`${base}/holds?${holdsQuery}`, csrf),
    ])
      .then(([ledger, holds]) => {
        if (!live) return;
        setLoaded({ key, ledger, holds });
        setFailedKey(null);
      })
      .catch((err: Error) => {
        if (!live) return;
        // Drop what was shown: after a failed refresh it may be stale too.
        setLoaded(null);
        setFailedKey(key);
        toast.error(err.message);
      });
    return () => {
      live = false;
    };
  }, [key, csrf, version]);

  const setMeter = useCallback((value: string) => {
    setMeterState(value);
    setPage(1);
  }, []);
  const setKind = useCallback((value: string) => {
    setKindState(value);
    setPage(1);
  }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const current = loaded?.key === key ? loaded : null;
  return {
    meter,
    setMeter,
    kind,
    setKind,
    page,
    setPage,
    ledger: current?.ledger ?? null,
    holds: current?.holds ?? null,
    failed: failedKey === key,
    refresh,
  };
}
