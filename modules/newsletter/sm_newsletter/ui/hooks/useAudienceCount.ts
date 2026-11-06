/**
 * How many confirmed subscribers an audience reaches, for the campaign editor.
 *
 * Debounced (`COUNT_DEBOUNCE_MS`) so a burst of changes is one request; the
 * request of a superseded audience is aborted and its answer ignored. An empty
 * `audience` (a choice not finished yet) asks nothing.
 */

import { useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';

export const COUNT_DEBOUNCE_MS = 300;

export function useAudienceCount(listKey: string, audience: string) {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [state, setState] = useState<{ count: number | null; error: string | null }>({
    count: null,
    error: null,
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!audience) {
      setState({ count: null, error: null });
      setLoading(false);
      return;
    }
    const abort = new AbortController();
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const { count } = await api.audienceCount(listKey, audience, abort.signal);
        if (abort.signal.aborted) return;
        setState({ count, error: null });
      } catch (e) {
        if (abort.signal.aborted) return;
        setState({ count: null, error: errorMessage(e, tRef.current) });
      }
      setLoading(false);
    }, COUNT_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [listKey, audience]);

  return { ...state, loading };
}
