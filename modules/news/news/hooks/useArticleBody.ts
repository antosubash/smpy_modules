/**
 * Load, autosave and publish an article's block document.
 *
 * The canvas used to be pagebuilder's, so this hook is the piece news did not
 * have: the body was that module's to load and save, and news only linked to
 * its editor. It owns the document now.
 */

import type { Data } from '@puckeditor/core';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  type ArticleDetail,
  getArticleDetail,
  publishArticle,
  saveArticleBody,
} from '../utils/api';

/** How long after the last edit a save fires.
 *
 * Long enough that typing a sentence is one request rather than thirty, short
 * enough that a writer who closes the tab loses a moment's work rather than a
 * paragraph.
 */
const AUTOSAVE_DELAY_MS = 1500;

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export function useArticleBody(articleId: number) {
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [data, setData] = useState<Data | null>(null);
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** The document as the server last accepted it, serialized.
   *
   * Compared against on every tick so an autosave only fires for a real
   * change. Without it Puck's `onChange` — which runs on selection as well as
   * on edit — would PUT the same bytes every time the writer clicked a block.
   */
  const savedRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Guards the state writes in `load` against a response that lands after the
   *  screen has moved on. */
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const detail = await getArticleDetail(articleId, signal);
        if (!aliveRef.current) return;
        setArticle(detail);
        const body = (detail.draft_data ?? {}) as unknown as Data;
        setData(body);
        savedRef.current = JSON.stringify(body);
      } catch (e) {
        if (signal?.aborted || !aliveRef.current) return;
        setError((e as Error).message);
      }
    },
    [articleId],
  );

  const flush = useCallback(
    async (next: Data) => {
      const serialized = JSON.stringify(next);
      if (serialized === savedRef.current) return;
      setSaveState('saving');
      try {
        const detail = await saveArticleBody(articleId, next as unknown as Record<string, unknown>);
        // Recorded only on success, so a failed save stays dirty and the next
        // tick retries it rather than treating the loss as settled.
        savedRef.current = serialized;
        if (detail) setArticle(detail);
        setSaveState('saved');
        setError(null);
      } catch (e) {
        setSaveState('error');
        setError((e as Error).message);
      }
    },
    [articleId],
  );

  /** Puck's `onChange`. Debounced — see `AUTOSAVE_DELAY_MS`. */
  const change = useCallback(
    (next: Data) => {
      setData(next);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(next), AUTOSAVE_DELAY_MS);
    },
    [flush],
  );

  /** Save now, without waiting for the timer — the toolbar's Save. */
  const saveNow = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (data) await flush(data);
  }, [data, flush]);

  const publish = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      // The pending draft goes first. Publishing snapshots whatever the server
      // holds, so skipping this would put the *previous* draft in front of
      // readers and leave the writer looking at something else entirely.
      await saveNow();
      await publishArticle(articleId);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [articleId, load, saveNow]);

  const dirty = data !== null && JSON.stringify(data) !== savedRef.current;

  return { article, data, saveState, error, busy, dirty, load, change, saveNow, publish };
}
