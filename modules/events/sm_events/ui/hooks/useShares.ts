import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText } from '../utils/api';
import { grantShare, listShares, revokeShare } from '../utils/api-shares';
import type { Share, ShareCandidate, ShareRole } from '../utils/types';
import { useCandidates } from './useCandidates';

export { MIN_QUERY } from './useCandidates';

export type Shares = {
  shares: Share[];
  candidates: ShareCandidate[];
  query: string;
  setQuery: (q: string) => void;
  /** The query is too short to search; the dialog says how many to type. */
  tooShort: boolean;
  loading: boolean;
  error: string | null;
  grant: (candidate: ShareCandidate, role: ShareRole) => Promise<void>;
  revoke: (share: Share) => Promise<void>;
};

/** The share dialog's state: current grants, and the picker's matches for
 *  `query` (people already holding a share are not offered again). Idle until
 *  `open`, so a closed dialog costs no requests. */
export function useShares(calendarId: string, open: boolean): Shares {
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
        if (current) setError(errorText(e));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      ++generation.current;
    };
  }, [open, refresh]);

  const grant = useCallback(
    async (candidate: ShareCandidate, role: ShareRole) => {
      await grantShare(calendarId, candidate.id, role);
      await refresh();
    },
    [calendarId, refresh],
  );

  const revoke = useCallback(
    async (share: Share) => {
      await revokeShare(share.id);
      await refresh();
    },
    [refresh],
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
    grant,
    revoke,
  };
}
