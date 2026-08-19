import { useCallback, useEffect, useRef, useState } from 'react';

import { type SearchResults, searchEverything } from '../utils/searchApi';

/** How long the field waits before asking the server.
 *
 * Longer than the article list's, because this query touches three tables and
 * scans page bodies — a request per keystroke would be expensive as well as
 * pointless.
 */
const DEBOUNCE_MS = 300;

/** Reads `?q=` so a search is a URL: linkable, and it survives a reload. */
function initialQuery(): string {
  if (typeof window === 'undefined') return '';
  return new URLSearchParams(window.location.search).get('q') ?? '';
}

export function useAdminSearch() {
  const [q, setQ] = useState(initialQuery);
  const [section, setSection] = useState('');
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only the newest response may write state: the debounce shortens the window
  // but does not close it, and a slow early query landing last would show
  // results for a search the user has already moved past.
  const latest = useRef(0);

  useEffect(() => {
    const trimmed = q.trim();
    if (!trimmed) {
      setResults(null);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      const request = ++latest.current;
      setLoading(true);
      searchEverything(trimmed, controller.signal)
        .then((response) => {
          if (request !== latest.current) return;
          setResults(response);
          setError(null);
        })
        .catch((e: Error) => {
          if (controller.signal.aborted || request !== latest.current) return;
          setError(e.message);
        })
        .finally(() => {
          if (request === latest.current) setLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q]);

  const setQuery = useCallback((next: string) => {
    setQ(next);
    if (typeof window === 'undefined') return;
    // `replaceState`, not push: stepping Back through every keystroke is not
    // what Back is for, and it would trap the user on the page.
    const url = next.trim()
      ? `${window.location.pathname}?q=${encodeURIComponent(next.trim())}`
      : window.location.pathname;
    window.history.replaceState(window.history.state, '', url);
  }, []);

  return { q, setQuery, results, loading, error, section, setSection };
}
