import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { grantShare, listShares, revokeShare } from '../utils/api-shares';
import { keys } from '../utils/i18n';
import type { Share, ShareCandidate, ShareRole } from '../utils/types';
import { useCandidates } from './useCandidates';

export { MIN_QUERY } from './useCandidates';

const GONE = keys.events.errors.calendar_gone;

type Shares = {
  shares: Share[];
  candidates: ShareCandidate[];
  query: string;
  setQuery: (q: string) => void;
  /** The query is too short to search; the dialog says how many to type. */
  tooShort: boolean;
  loading: boolean;
  error: string | null;
  /** Only the failure to load the current grants (never the picker's). */
  listError: string | null;
  grant: (candidate: ShareCandidate, role: ShareRole) => Promise<void>;
  revoke: (share: Share) => Promise<void>;
};

/** The share dialog's state: current grants, and the picker's matches for
 *  `query` (people already holding a share are not offered again). Idle until
 *  `open`, so a closed dialog costs no requests. */
export function useShares(calendarId: string, open: boolean, onGone?: () => void): Shares {
  // Read through a ref: a caller's callback is usually a new function each render.
  const gone = useRef(onGone);
  gone.current = onGone;
  const [shares, setShares] = useState<Share[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const search = useCandidates(calendarId, open, query);

  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const mine = ++generation.current;
    const rows = await listShares(calendarId);
    if (mine === generation.current) setShares(rows);
  }, [calendarId]);

  useEffect(() => {
    if (!open) return;
    let current = true;
    setLoading(true);
    refresh()
      .then(() => {
        if (current) setError(null);
      })
      .catch((e) => {
        if (!current) return;
        setError(errorText(e, GONE));
        if (isGone(e)) gone.current?.();
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      ++generation.current;
    };
  }, [open, refresh]);

  /** A write that finds the calendar gone refreshes the list before it throws. */
  const settle = useCallback(async (write: Promise<unknown>) => {
    try {
      await write;
    } catch (e) {
      if (isGone(e)) gone.current?.();
      throw e;
    }
  }, []);

  const grant = useCallback(
    async (candidate: ShareCandidate, role: ShareRole) => {
      await settle(grantShare(calendarId, candidate.id, role));
      await refresh();
    },
    [calendarId, refresh, settle],
  );

  const revoke = useCallback(
    async (share: Share) => {
      await settle(revokeShare(share.id));
      await refresh();
    },
    [refresh, settle],
  );

  const held = new Set(shares.map((s) => s.subject_id));
  return {
    shares,
    candidates: search.candidates.filter((c) => !held.has(c.id)),
    query,
    setQuery,
    tooShort: search.tooShort,
    loading,
    error: search.error ?? error,
    listError: error,
    grant,
    revoke,
  };
}
