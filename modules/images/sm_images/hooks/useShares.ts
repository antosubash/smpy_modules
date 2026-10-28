import { useCallback, useEffect, useState } from 'react';

import { grantShare, listShares, revokeShare, shareCandidates } from '../utils/api-shares';
import type { Share, ShareCandidate, ShareRole } from '../utils/types';

const SEARCH_DELAY_MS = 250;

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export type Shares = {
  shares: Share[];
  candidates: ShareCandidate[];
  query: string;
  setQuery: (q: string) => void;
  loading: boolean;
  error: string | null;
  grant: (candidate: ShareCandidate, role: ShareRole) => Promise<void>;
  revoke: (share: Share) => Promise<void>;
};

/** The share dialog's state: current grants, and the picker's matches for
 *  `query` (people already holding a share are not offered again). Idle until
 *  `open`, so a closed dialog costs no requests. */
export function useShares(collectionId: string, open: boolean): Shares {
  const [shares, setShares] = useState<Share[]>([]);
  const [found, setFound] = useState<ShareCandidate[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setShares(await listShares(collectionId));
  }, [collectionId]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    refresh()
      .then(() => setError(null))
      .catch((e) => setError(message(e)))
      .finally(() => setLoading(false));
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    let current = true;
    const timer = window.setTimeout(() => {
      shareCandidates(collectionId, query.trim())
        .then((rows) => current && setFound(rows))
        .catch((e) => current && setError(message(e)));
    }, SEARCH_DELAY_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [open, collectionId, query]);

  const grant = useCallback(
    async (candidate: ShareCandidate, role: ShareRole) => {
      await grantShare(collectionId, candidate.id, role);
      await refresh();
    },
    [collectionId, refresh],
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
    candidates: found.filter((c) => !held.has(c.id)),
    query,
    setQuery,
    loading,
    error,
    grant,
    revoke,
  };
}
