import { useCallback, useEffect, useState } from 'react';
import { isGone } from '../utils/api';
import {
  type Capacity,
  deleteSubscription,
  listSubscriptions,
  pauseSubscription,
  refreshSubscription,
  resumeSubscription,
  type Subscription,
  subscriptionCapacity,
  subscriptionErrorText,
} from '../utils/api-subscriptions';
import { keys, translate } from '../utils/i18n';
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
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [capacity, setCapacity] = useState<Capacity | null>(null);

  const load = useCallback(async () => {
    const request = begin();
    setLoading(true);
    try {
      const rows = await listSubscriptions(calendarId, request.signal);
      if (!request.alive()) return;
      setItems(rows);
      setError(null);
      // How much room is left is only a hint for the Add button (the server decides): a failure
      // to read it leaves the button as it was.
      subscriptionCapacity(calendarId, request.signal)
        .then((room) => request.alive() && setCapacity(room))
        .catch(() => undefined);
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
      setNotes(({ [id]: _gone, ...rest }) => rest);
      try {
        const answer = await run[action](id);
        if (action === 'refresh' && answer && (answer as Subscription).queued) {
          const minutes = (answer as Subscription).queued_minutes ?? 2;
          setNotes((now) => ({
            ...now,
            [id]: translate(keys.events.subscriptions.row.queued, { minutes }),
          }));
        }
      } catch (e) {
        setRowError((now) => ({ ...now, [id]: subscriptionErrorText(e) }));
      }
      await load();
    },
    [load],
  );
  return { items, loading, error, rowError, notes, capacity, reload: load, act };
}
