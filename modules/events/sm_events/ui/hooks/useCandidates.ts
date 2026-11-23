import { useEffect, useState } from 'react';
import { ApiError, isGone, searchErrorText } from '../utils/api';
import { shareCandidates } from '../utils/api-shares';
import { keys } from '../utils/i18n';
import type { ShareCandidate } from '../utils/types';
import { useGoneOnce, useRequestScope } from './useRequestScope';

export const MIN_QUERY = 3;

type Result = {
  term: string;
  candidates: ShareCandidate[];
  error: string | null;
  /** A 429: its wait message outlives a change of query (even one too short to
   *  search), until a response replaces it or the dialog closes. */
  limited: boolean;
};

/** The picker's matches for `query`. `onGone` runs (at most once per open
 *  dialog, never after it closes) when the search finds the calendar gone, so
 *  the caller refreshes its list. `settled` is false while a request is
 *  debouncing or in flight: the dialog must not say "No one found" then. */
export function useCandidates(
  calendarId: string,
  open: boolean,
  query: string,
  onGone?: () => void,
) {
  const gone = useGoneOnce(open, onGone);
  const begin = useRequestScope(open);
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
      const request = begin();
      const fresh = () => current && request.alive();
      shareCandidates(calendarId, term, request.signal)
        .then((candidates) => {
          if (fresh()) setResult({ term, candidates, error: null, limited: false });
        })
        .catch((e) => {
          if (!fresh()) return;
          setResult({
            term,
            candidates: [],
            error: searchErrorText(e, keys.events.errors.calendar_gone),
            limited: e instanceof ApiError && e.status === 429,
          });
          if (isGone(e)) gone();
        });
    }, 250);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [calendarId, open, term, tooShort, begin, gone]);
  const live = open && !tooShort;
  const settled = live && result?.term === term;
  const waiting = open && !settled && result?.limited === true;
  return {
    tooShort,
    settled,
    candidates: settled ? result.candidates : [],
    error: settled || waiting ? (result?.error ?? null) : null,
  };
}
