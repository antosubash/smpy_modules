import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ADMIN_API, api } from '../utils/api';
import type { Paged, UsageEvent, UsageHold } from '../utils/types';

export const USAGE_API = `${ADMIN_API}/usage`;
const LEDGER_PER_PAGE = 20;

/**
 * One organisation's ledger page and open holds, for the usage drawer.
 *
 * Fetched when the drawer opens and again whenever a filter, the page or
 * `refresh()` changes; a response for a tenant the drawer has since left is
 * dropped. `null` tenant: nothing loads.
 */
export function useUsageDetail(tenantId: string | null, csrf: string, initialMeter = '') {
  const [meter, setMeterState] = useState(initialMeter);
  const [kind, setKindState] = useState('');
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [ledger, setLedger] = useState<Paged<UsageEvent> | null>(null);
  const [holds, setHolds] = useState<UsageHold[] | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: start over when the drawer opens on another tenant
  useEffect(() => {
    setMeterState(initialMeter);
    setKindState('');
    setPage(1);
    setLedger(null);
    setHolds(null);
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
      .then(([nextLedger, nextHolds]) => {
        if (!live) return;
        setLedger(nextLedger);
        setHolds(nextHolds);
      })
      .catch((err: Error) => live && toast.error(err.message));
    return () => {
      live = false;
    };
  }, [tenantId, csrf, meter, kind, page, version]);

  const setMeter = useCallback((value: string) => {
    setMeterState(value);
    setPage(1);
  }, []);
  const setKind = useCallback((value: string) => {
    setKindState(value);
    setPage(1);
  }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  return { meter, setMeter, kind, setKind, page, setPage, ledger, holds, refresh };
}
