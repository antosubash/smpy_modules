import { useCallback, useEffect, useState } from 'react';
import { getRegistrationCounts } from '../utils/api-events';
import type { RegistrationCount } from '../utils/types-events';

export type CountsState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; items: RegistrationCount[] };

/** Seats taken per date for a saved event, loaded when `enabled`. A failure is a state with a
 *  retry, never a thrown error: the counts are information, not part of saving. */
export function useRegistrationCounts(
  eventId: string | null,
  enabled: boolean,
  /** Changes when the event is saved (its revision): the counts are read again. */
  version: number | string = 0,
) {
  const [state, setState] = useState<CountsState>({ kind: 'idle' });
  const [attempt, setAttempt] = useState(0);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` only re-runs the load
  useEffect(() => {
    if (!eventId || !enabled) {
      setState({ kind: 'idle' });
      return;
    }
    const controller = new AbortController();
    setState({ kind: 'loading' });
    getRegistrationCounts(eventId, controller.signal).then(
      (page) => {
        if (!controller.signal.aborted) setState({ kind: 'ready', items: page.items });
      },
      () => {
        if (!controller.signal.aborted) setState({ kind: 'error' });
      },
    );
    return () => controller.abort();
  }, [eventId, enabled, attempt, version]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}
