/**
 * The report of a campaign: one fetch on mount; while the answer says `sending`
 * it is re-fetched every `REPORT_POLL_MS`, and polling stops as soon as an
 * answer reports any other status. Unmounting aborts the request in flight.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { Report } from '../utils/types';

export const REPORT_POLL_MS = 60_000;

export function useCampaignReport(id: number) {
  const { t } = useT();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  /** Fetches once; resolves to the answer, or null on failure or abort. */
  const fetchOnce = useCallback(
    async (signal: AbortSignal): Promise<Report | null> => {
      try {
        const next = await api.report(id, signal);
        if (signal.aborted) return null;
        setReport(next);
        setError(null);
        return next;
      } catch (e) {
        if (!signal.aborted) setError(errorMessage(e, tRef.current));
        return null;
      }
    },
    [id],
  );

  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let sending = false;
    const loop = async () => {
      const next = await fetchOnce(abort.signal);
      if (abort.signal.aborted) return;
      // If the first fetch fails nothing polls; the Refresh button (reload) retries.
      // A failed poll keeps the last known state, so a blip does not end the polling.
      if (next) sending = next.status === 'sending';
      if (sending) timer = setTimeout(() => void loop(), REPORT_POLL_MS);
    };
    void loop();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [fetchOnce]);

  const reload = useCallback(async () => {
    await fetchOnce((controller.current ?? new AbortController()).signal);
  }, [fetchOnce]);

  return { report, error, reload };
}
