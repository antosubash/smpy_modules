import { useCallback, useEffect, useRef, useState } from 'react';

import { listPromptResults } from '../utils/api-prompts';
import type { PromptResult } from '../utils/types-prompts';

/** How often, and how many times, results are re-read while a run is in flight. */
export const POLL_MS = 3000;
export const POLL_LIMIT = 20;

const ACTIVE = new Set(['pending', 'running']);

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export type PromptResults = {
  rows: PromptResult[] | null;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
};

/** `fresh` (the first page again) over `shown`: a row it has replaces the shown
 *  one in place; one not shown yet goes first; the later pages stay. */
function merge(shown: PromptResult[], fresh: PromptResult[]): PromptResult[] {
  const byId = new Map(fresh.map((r) => [r.id, r]));
  const kept = shown.map((r) => byId.get(r.id) ?? r);
  const known = new Set(shown.map((r) => r.id));
  return [...fresh.filter((r) => !known.has(r.id)), ...kept];
}

/**
 * A prompt's results, paged by cursor ("load more"). ``version`` is bumped by
 * whoever launches a run: the first page is read again then. While any shown
 * row is ``pending`` or ``running`` the first page is re-read every
 * :data:`POLL_MS` (at most :data:`POLL_LIMIT` times), so a run that settles -
 * or fails - replaces what the panel showed before it.
 */
export function usePromptResults(promptId: string, version: number): PromptResults {
  const [rows, setRows] = useState<PromptResult[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polls, setPolls] = useState(0);
  const latest = useRef(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `version` asks for a fresh read
  useEffect(() => {
    const ticket = ++latest.current;
    setPolls(0);
    listPromptResults(promptId)
      .then((page) => {
        if (ticket !== latest.current) return;
        setRows(page.items);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((e) => setError(message(e)));
  }, [promptId, version]);

  const active = rows?.some((r) => ACTIVE.has(r.status)) ?? false;
  useEffect(() => {
    if (!active || polls >= POLL_LIMIT) return;
    const timer = window.setTimeout(() => {
      const ticket = latest.current;
      listPromptResults(promptId)
        .then((page) => {
          if (ticket !== latest.current) return;
          setRows((shown) => merge(shown ?? [], page.items));
          setPolls((n) => n + 1);
        })
        .catch((e) => setError(message(e)));
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [active, polls, promptId]);

  const loadMore = useCallback(() => {
    if (cursor === null) return;
    const ticket = latest.current;
    listPromptResults(promptId, cursor)
      .then((page) => {
        if (ticket !== latest.current) return;
        setRows((shown) => [...(shown ?? []), ...page.items]);
        setCursor(page.next_cursor);
      })
      .catch((e) => setError(message(e)));
  }, [promptId, cursor]);

  return { rows, error, hasMore: cursor !== null, loadMore };
}
