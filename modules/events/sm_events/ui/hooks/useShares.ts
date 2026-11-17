import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { grantShare, listShares, revokeShare } from '../utils/api-shares';
import { keys } from '../utils/i18n';
import type { Share, ShareCandidate, ShareRole } from '../utils/types';
import { useCandidates } from './useCandidates';
import { type ScopedRequest, useGoneOnce, useRequestScope } from './useRequestScope';

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
  /** Resolve `false` when the dialog closed meanwhile: nothing to report then. */
  grant: (candidate: ShareCandidate, role: ShareRole) => Promise<boolean>;
  revoke: (share: Share) => Promise<boolean>;
};

/** The share dialog's state: current grants, and the picker's matches for
 *  `query` (people already holding a share are not offered again). Idle until
 *  `open`, so a closed dialog costs no requests. */
export function useShares(calendarId: string, open: boolean, onGone?: () => void): Shares {
  const gone = useGoneOnce(open, onGone);
  const begin = useRequestScope(open);
  const [shares, setShares] = useState<Share[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const search = useCandidates(calendarId, open, query, gone);
  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  // Orders the live refreshes among themselves; the scope retires the old ones.
  const generation = useRef(0);
  const refresh = useCallback(
    async (request: ScopedRequest) => {
      const mine = ++generation.current;
      const rows = await listShares(calendarId, request.signal);
      if (request.alive() && mine === generation.current) setShares(rows);
    },
    [calendarId],
  );

  const load = useCallback(() => {
    const request = begin();
    setLoading(true);
    return refresh(request)
      .then(() => {
        if (request.alive()) setError(null);
      })
      .catch((e) => {
        if (!request.alive()) return;
        setError(errorText(e, GONE));
        if (isGone(e)) gone();
      })
      .finally(() => {
        if (request.alive()) setLoading(false);
      });
  }, [begin, refresh, gone]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  /** A write that finds the calendar gone refreshes the list before it throws.
   *  A write that outlives the dialog neither throws nor reports: `false`. */
  const settle = useCallback(
    async (request: ScopedRequest, write: Promise<unknown>): Promise<boolean> => {
      try {
        await write;
      } catch (e) {
        if (!request.alive()) return false;
        if (isGone(e)) gone();
        throw e;
      }
      return request.alive();
    },
    [gone],
  );

  const grant = useCallback(
    async (candidate: ShareCandidate, role: ShareRole) => {
      const request = begin();
      if (!(await settle(request, grantShare(calendarId, candidate.id, role)))) return false;
      return settle(request, refresh(request));
    },
    [begin, calendarId, refresh, settle],
  );

  const revoke = useCallback(
    async (share: Share) => {
      const request = begin();
      // A grant that is already gone (another tab revoked it) is no error and
      // says nothing about the calendar: the reload drops the stale row. Only
      // that reload finding the calendar gone is "no longer exists".
      try {
        await revokeShare(share.id);
      } catch (e) {
        if (!request.alive()) return false;
        if (!isGone(e)) throw e;
      }
      if (!request.alive()) return false;
      return settle(request, refresh(request));
    },
    [begin, refresh, settle],
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
