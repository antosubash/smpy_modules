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
  /** The picker's failure: independent of the grants list. */
  searchError: string | null;
  /** The picker has answered for this query (no empty state before). */
  searchSettled: boolean;
  /** Only the failure to load the current grants (never the picker's). */
  listError: string | null;
  /** Load the grants again after a failure. */
  retry: () => void;
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
  const search = useCandidates(calendarId, open, query, onGone);

  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const mine = ++generation.current;
    const rows = await listShares(calendarId);
    if (mine === generation.current) setShares(rows);
  }, [calendarId]);

  const load = useCallback(
    (alive: () => boolean = () => true) => {
      setLoading(true);
      return refresh()
        .then(() => {
          if (alive()) setError(null);
        })
        .catch((e) => {
          if (!alive()) return;
          setError(errorText(e, GONE));
          if (isGone(e)) gone.current?.();
        })
        .finally(() => {
          if (alive()) setLoading(false);
        });
    },
    [refresh],
  );

  useEffect(() => {
    if (!open) return;
    let current = true;
    void load(() => current);
    return () => {
      current = false;
      ++generation.current;
    };
  }, [open, load]);

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
      await settle(refresh());
    },
    [calendarId, refresh, settle],
  );

  const revoke = useCallback(
    async (share: Share) => {
      // A grant that is already gone (another tab revoked it) is no error and
      // says nothing about the calendar: the reload drops the stale row. Only
      // that reload finding the calendar gone is "no longer exists".
      try {
        await revokeShare(share.id);
      } catch (e) {
        if (!isGone(e)) throw e;
      }
      await settle(refresh());
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
    searchError: search.error,
    searchSettled: search.settled,
    listError: error,
    retry: () => void load(),
    grant,
    revoke,
  };
}
