import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText } from '../utils/api-net';
import { listPromptResults, type PromptResultPage } from '../utils/api-prompts';
import type { PromptResult } from '../utils/types-prompts';

/** How often, and how many times, results are re-read while a run is in flight. */
export const POLL_MS = 3000;
export const POLL_LIMIT = 20;
/** Polls a launch always gets: a queued run may not have written its rows yet. */
export const LAUNCH_POLLS = 3;

const ACTIVE = new Set(['pending', 'running']);

/** Every page from the start until at least `count` rows are read (or none
 *  are left): what is on screen, read again - later pages included. */
async function readThrough(promptId: string, count: number): Promise<PromptResultPage> {
  let page = await listPromptResults(promptId);
  const items = [...page.items];
  while (items.length < count && page.next_cursor !== null) {
    page = await listPromptResults(promptId, page.next_cursor);
    items.push(...page.items);
  }
  return { items, next_cursor: page.next_cursor };
}

export type PromptResults = {
  rows: PromptResult[] | null;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
};

/**
 * A prompt's results, paged by cursor ("load more"). ``version`` is bumped by
 * whoever launches a run: the first page is read again then, and polling
 * starts whatever that read shows - a queued run may not have written a row
 * yet. Polling re-reads every page on screen every :data:`POLL_MS`; it goes on
 * while any row is ``pending`` or ``running`` (or for :data:`LAUNCH_POLLS`
 * after a launch) and never past :data:`POLL_LIMIT`.
 */
export function usePromptResults(promptId: string, version: number): PromptResults {
  const [rows, setRows] = useState<PromptResult[] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polls, setPolls] = useState(0);
  const [launched, setLaunched] = useState(false);
  const latest = useRef(0);
  const shown = useRef(0);
  // Bumped whenever the shown rows are committed and when a "load more" starts:
  // a read that began under an older value is a stale snapshot and is dropped.
  const snapshot = useRef(0);
  // The "load more" in flight, if any. A poll waits for it, so the two never
  // overlap: the poll then re-reads every page now on screen.
  const paging = useRef<Promise<void> | null>(null);
  shown.current = rows?.length ?? 0;

  useEffect(() => {
    const ticket = ++latest.current;
    setPolls(0);
    setLaunched(version > 0);
    listPromptResults(promptId)
      .then((page) => {
        if (ticket !== latest.current) return;
        snapshot.current += 1;
        setRows(page.items);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((e) => setError(errorText(e)));
  }, [promptId, version]);

  const active = rows?.some((r) => ACTIVE.has(r.status)) ?? false;
  const polling = rows !== null && (active || (launched && polls < LAUNCH_POLLS));
  useEffect(() => {
    if (!polling || polls >= POLL_LIMIT) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      await paging.current;
      if (cancelled) return;
      const ticket = latest.current;
      const started = snapshot.current;
      readThrough(promptId, shown.current)
        .then((page) => {
          if (ticket !== latest.current) return;
          if (started === snapshot.current) {
            snapshot.current += 1;
            shown.current = page.items.length;
            setRows(page.items);
            setCursor(page.next_cursor);
          } // else a "load more" came first: its rows stay; this poll still counts
          setPolls((n) => n + 1);
        })
        .catch((e) => setError(errorText(e)));
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [polling, polls, promptId]);

  const loadMore = useCallback(() => {
    if (cursor === null || paging.current) return;
    const ticket = latest.current;
    const started = ++snapshot.current;
    const request = listPromptResults(promptId, cursor)
      .then((page) => {
        if (ticket !== latest.current || started !== snapshot.current) return;
        snapshot.current += 1;
        shown.current += page.items.length;
        setRows((before) => [...(before ?? []), ...page.items]);
        setCursor(page.next_cursor);
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => {
        if (paging.current === request) paging.current = null;
      });
    paging.current = request;
  }, [promptId, cursor]);

  return { rows, error, hasMore: cursor !== null, loadMore };
}
