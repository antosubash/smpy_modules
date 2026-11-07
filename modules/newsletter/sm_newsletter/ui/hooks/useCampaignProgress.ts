/**
 * Live delivery counts for a campaign that is scheduled or sending.
 *
 * One fetch on mount (and whenever the id or status changes; none for a draft); while the
 * campaign is `scheduled` or `sending` the latest answer is re-fetched every
 * `PROGRESS_POLL_MS`, and polling stops as soon as an answer reports any other
 * status. Unmounting aborts the request in flight.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { Progress } from '../utils/types';

export const PROGRESS_POLL_MS = 10_000;

const LIVE = new Set(['scheduled', 'sending']);

export function useCampaignProgress(id: number, status: string | undefined) {
  const { t } = useT();
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  /** Fetches once; resolves to the answer, or null on failure or abort. */
  const fetchOnce = useCallback(
    async (signal: AbortSignal): Promise<Progress | null> => {
      try {
        const next = await api.progress(id, signal);
        if (signal.aborted) return null;
        setProgress(next);
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
    // A draft has no send rows to count; the panel shows nothing for it.
    if (status === undefined || status === 'draft') return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      const next = await fetchOnce(abort.signal);
      if (abort.signal.aborted) return;
      // Keep polling through a failed fetch; stop once the answer leaves the live states.
      const live = next ? LIVE.has(next.status) : LIVE.has(status);
      if (live) timer = setTimeout(() => void loop(), PROGRESS_POLL_MS);
    };
    void loop();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [fetchOnce, status]);

  return { progress, error };
}
