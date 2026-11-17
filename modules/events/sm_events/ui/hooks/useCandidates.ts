import { useEffect, useState } from 'react';
import { errorText } from '../utils/api';
import { shareCandidates } from '../utils/api-shares';
import type { ShareCandidate } from '../utils/types';

export const MIN_QUERY = 3;
export function useCandidates(calendarId: string, open: boolean, query: string) {
  const term = query.trim();
  const tooShort = [...term].length < MIN_QUERY;
  const [result, setResult] = useState<{
    term: string;
    candidates: ShareCandidate[];
    error: string | null;
  } | null>(null);
  useEffect(() => {
    if (!open || tooShort) return;
    let current = true;
    const timer = window.setTimeout(() => {
      shareCandidates(calendarId, term)
        .then((candidates) => {
          if (current) setResult({ term, candidates, error: null });
        })
        .catch((e) => {
          if (current) setResult({ term, candidates: [], error: errorText(e) });
        });
    }, 250);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [calendarId, open, term, tooShort]);
  const visible = open && !tooShort && result?.term === term;
  return {
    tooShort,
    candidates: visible ? result.candidates : [],
    error: visible ? result.error : null,
  };
}
