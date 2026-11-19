import { useCallback, useEffect, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import {
  type CreatedFeedToken,
  createToken,
  type FeedToken,
  listTokens,
  revokeToken,
} from '../utils/api-feeds';
import { keys } from '../utils/i18n';
import { useGoneOnce, useRequestScope } from './useRequestScope';

type FeedTokens = {
  /** The caller's own links. */
  mine: FeedToken[];
  /** Everyone's (only asked for with `canManage`), else `null`. */
  everyone: FeedToken[] | null;
  loading: boolean;
  error: string | null;
  /** Create a link and re-read the lists. The link itself is **returned**, never stored here:
   *  the list state only ever holds what a list call returned, which has no secret. `null`
   *  when the dialog closed meanwhile. */
  create: (input: { label: string; locale: string | null }) => Promise<CreatedFeedToken | null>;
  revoke: (token: FeedToken) => Promise<boolean>;
};

/** The Subscribe dialog's links. Idle until `open`, so a closed dialog costs no requests. */
export function useFeedTokens(
  calendarId: string,
  open: boolean,
  canManage: boolean,
  onGone?: () => void,
): FeedTokens {
  const gone = useGoneOnce(open, onGone);
  const begin = useRequestScope(open);
  const [mine, setMine] = useState<FeedToken[]>([]);
  const [everyone, setEveryone] = useState<FeedToken[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const request = begin();
    setLoading(true);
    try {
      const [own, all] = await Promise.all([
        listTokens(calendarId, false, request.signal),
        canManage ? listTokens(calendarId, true, request.signal) : Promise.resolve(null),
      ]);
      if (!request.alive()) return;
      setMine(own);
      setEveryone(all);
      setError(null);
    } catch (e) {
      if (!request.alive()) return;
      setError(errorText(e, keys.events.errors.calendar_gone));
      if (isGone(e)) gone();
    } finally {
      if (request.alive()) setLoading(false);
    }
  }, [begin, calendarId, canManage, gone]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const create = useCallback(
    async (input: { label: string; locale: string | null }) => {
      const request = begin();
      const created = await createToken(calendarId, input);
      if (!request.alive()) return null;
      await load();
      return created;
    },
    [begin, calendarId, load],
  );

  const revoke = useCallback(
    async (token: FeedToken) => {
      const request = begin();
      await revokeToken(token.id);
      if (!request.alive()) return false;
      await load();
      return true;
    },
    [begin, load],
  );

  return { mine, everyone, loading, error, create, revoke };
}
