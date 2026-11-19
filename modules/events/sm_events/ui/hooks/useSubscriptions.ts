import { useCallback, useEffect, useState } from 'react';
import { isGone } from '../utils/api';
import {
  deleteSubscription,
  listSubscriptions,
  pauseSubscription,
  refreshSubscription,
  resumeSubscription,
  type Subscription,
  subscriptionErrorText,
} from '../utils/api-subscriptions';
import { useGoneOnce, useRequestScope } from './useRequestScope';

type Action = 'refresh' | 'pause' | 'resume' | 'delete';
const run = {
  refresh: refreshSubscription,
  pause: pauseSubscription,
  resume: resumeSubscription,
  delete: deleteSubscription,
} as const;

/** The Subscriptions dialog's list: idle until `open`, re-read after every change. A row action
 *  that fails answers with its message (`rowError`, keyed by subscription) and leaves the list. */
export function useSubscriptions(calendarId: string, open: boolean, onGone?: () => void) {
  const gone = useGoneOnce(open, onGone);
  const begin = useRequestScope(open);
  const [items, setItems] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const request = begin();
    setLoading(true);
    try {
      const rows = await listSubscriptions(calendarId, request.signal);
      if (!request.alive()) return;
      setItems(rows);
      setError(null);
    } catch (e) {
      if (!request.alive()) return;
      if (isGone(e)) gone();
      else setError(subscriptionErrorText(e));
    } finally {
      if (request.alive()) setLoading(false);
    }
  }, [calendarId, begin, gone]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const act = useCallback(
    async (id: string, action: Action) => {
      setRowError(({ [id]: _dropped, ...rest }) => rest);
      try {
        await run[action](id);
      } catch (e) {
        setRowError((now) => ({ ...now, [id]: subscriptionErrorText(e) }));
      }
      await load();
    },
    [load],
  );
  return { items, loading, error, rowError, reload: load, act };
}
