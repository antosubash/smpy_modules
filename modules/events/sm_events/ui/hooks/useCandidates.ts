import { useEffect, useRef, useState } from 'react';
import { ApiError, errorText, isGone } from '../utils/api';
import { shareCandidates } from '../utils/api-shares';
import { keys } from '../utils/i18n';
import type { ShareCandidate } from '../utils/types';

export const MIN_QUERY = 3;

type Result = {
  term: string;
  candidates: ShareCandidate[];
  error: string | null;
  /** A 429: its wait message outlives a change of query, until a response replaces it. */
  limited: boolean;
};

/** The picker's matches for `query`. `onGone` runs when the search finds the
 *  calendar gone, so the caller refreshes its list (a ref: it may be new each
 *  render). `settled` is false while a request is debouncing or in flight:
 *  the dialog must not say "No one found" then. */
export function useCandidates(
  calendarId: string,
  open: boolean,
  query: string,
  onGone?: () => void,
) {
  const gone = useRef(onGone);
  gone.current = onGone;
  const term = query.trim();
  const tooShort = [...term].length < MIN_QUERY;
  const [result, setResult] = useState<Result | null>(null);
  useEffect(() => {
    if (!open) setResult(null);
  }, [open]);
  useEffect(() => {
    if (!open || tooShort) return;
    let current = true;
    const timer = window.setTimeout(() => {
      shareCandidates(calendarId, term)
        .then((candidates) => {
          if (current) setResult({ term, candidates, error: null, limited: false });
        })
        .catch((e) => {
          if (!current) return;
          setResult({
            term,
            candidates: [],
            error: errorText(e, keys.events.errors.calendar_gone),
            limited: e instanceof ApiError && e.status === 429,
          });
          if (isGone(e)) gone.current?.();
        });
    }, 250);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [calendarId, open, term, tooShort]);
  const live = open && !tooShort;
  const settled = live && result?.term === term;
  const waiting = live && !settled && result?.limited === true;
  return {
    tooShort,
    settled,
    candidates: settled ? result.candidates : [],
    error: settled || waiting ? (result?.error ?? null) : null,
  };
}
