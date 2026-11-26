import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, errorText, isGone } from '../utils/api';
import {
  deleteFollow,
  type Follow,
  getFollow,
  type Lead,
  type ReminderStatus,
  reminderStatusOnce,
  setFollow,
} from '../utils/api-reminders';
import { useT } from '../utils/i18n';

/** `loading`; `unavailable` (reminders cannot be delivered, with the manager-only reason);
 *  `hidden` (the event is gone for this user: nothing to show); `ready`. */
export type FollowState =
  | { kind: 'loading' }
  | { kind: 'unavailable'; reason: string | null }
  | { kind: 'hidden' }
  | { kind: 'ready'; status: ReminderStatus; follow: Follow };

/** One event's follow for the signed-in caller: loaded once, changed optimistically and put back
 *  when the server refuses. */
export function useFollow(eventId: string) {
  const [state, setState] = useState<FollowState>({ kind: 'loading' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [atCap, setAtCap] = useState(false);
  const alive = useRef(true);
  // The page's translator: this runs on public event pages too (#417).
  const { t } = useT();

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    (async () => {
      try {
        const status = await reminderStatusOnce();
        if (!alive.current) return;
        if (!status.available) {
          setState({ kind: 'unavailable', reason: status.reason ?? null });
          return;
        }
        const follow = await getFollow(eventId, controller.signal);
        if (alive.current) setState({ kind: 'ready', status, follow });
      } catch (e) {
        if (!alive.current) return;
        // Gone, signed out or refused: there is nothing to offer. Anything else (the network):
        // say reminders are unavailable rather than leave a control that does nothing.
        const status = (e as { status?: number }).status;
        setState(
          isGone(e) || status === 401 || status === 403
            ? { kind: 'hidden' }
            : { kind: 'unavailable', reason: null },
        );
      }
    })();
    return () => {
      alive.current = false;
      controller.abort();
    };
  }, [eventId]);

  /** Make `leads` the whole set (empty stops). Optimistic; `false` when it was refused. */
  const save = useCallback(
    async (leads: Lead[]): Promise<boolean> => {
      if (state.kind !== 'ready' || saving) return false;
      const before = state;
      setError(null);
      setAtCap(false);
      setSaving(true);
      setState({ ...before, follow: { ...before.follow, leads, next_due: {} } });
      try {
        const follow =
          leads.length === 0 ? await stop(eventId, before.follow) : await setFollow(eventId, leads);
        if (alive.current) setState({ ...before, follow });
        return true;
      } catch (e) {
        if (!alive.current) return false;
        setState(before); // put back what the server did not accept
        if (isGone(e)) setState({ kind: 'hidden' });
        else {
          setError(errorText(e, undefined, t));
          setAtCap(e instanceof ApiError && e.code === 'follow_limit');
        }
        return false;
      } finally {
        if (alive.current) setSaving(false);
      }
    },
    [eventId, saving, state, t],
  );

  return {
    state,
    saving,
    error,
    atCap,
    save,
    clearError: () => {
      setError(null);
      setAtCap(false);
    },
  };
}

/** Stopping is a DELETE (always allowed, even while reminders are unavailable). */
async function stop(eventId: string, before: Follow): Promise<Follow> {
  await deleteFollow(eventId);
  return { ...before, leads: [], next_due: {}, deliverable: before.deliverable };
}
