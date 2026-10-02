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
import { isHttpStatus } from '../utils/http';
import { useInFlight } from './useInFlight';

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
  const { busy, run: guard } = useInFlight();
  /** The server refused a write because the article changed elsewhere. The
   *  edit stays on screen; nothing more is sent until the writer reloads. */
  const [conflict, setConflict] = useState(false);
  /** Bumped by `reload` so the canvas remounts on the server's document. */
  const [reloadKey, setReloadKey] = useState(0);
  const conflictRef = useRef(false);
  /** `updated_at` as last loaded or accepted — what every write is made against. */
  const updatedAtRef = useRef<string | null>(null);

  /** The document as the server last accepted it, serialized.
   *
   * Compared against on every tick so an autosave only fires for a real
   * change. Without it Puck's `onChange` — which runs on selection as well as
   * on edit — would PUT the same bytes every time the writer clicked a block.
   */
  const savedRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** The edit the debounce timer is waiting to save, if any. */
  const pendingRef = useRef<Data | null>(null);
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
        updatedAtRef.current = detail.updated_at ?? null;
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

  /** One save at a time. The timer, Save, Publish and unmount can all flush;
   *  overlapping, the later request would carry the `updated_at` from before
   *  the earlier one landed and be refused as a conflict with itself. */
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());

  /** One request; `flush` is what callers use. Reads the refs at send time,
   *  so a queued save carries whatever the previous one left behind. */
  const send = useCallback(
    async (next: Data): Promise<boolean> => {
      const serialized = JSON.stringify(next);
      if (serialized === savedRef.current) return true;
      // Held until Reload: retrying a stale write would only be refused again,
      // and force-sending it would overwrite what the other writer saved.
      if (conflictRef.current) {
        pendingRef.current = next;
        return false;
      }
      setSaveState('saving');
      try {
        const detail = await saveArticleBody(
          articleId,
          next as unknown as Record<string, unknown>,
          updatedAtRef.current,
        );
        // Recorded only on success, so a failed save stays dirty and the next
        // tick retries it rather than treating the loss as settled.
        savedRef.current = serialized;
        if (detail) {
          setArticle(detail);
          updatedAtRef.current = detail.updated_at ?? updatedAtRef.current;
        }
        setSaveState('saved');
        setError(null);
        return true;
      } catch (e) {
        setSaveState('error');
        if (isHttpStatus(e, 409)) {
          conflictRef.current = true;
          setConflict(true);
        }
        setError((e as Error).message);
        // Still unsaved, so leaving the screen gets one more try at it.
        if (pendingRef.current === null) pendingRef.current = next;
        return false;
      }
    },
    [articleId],
  );

  /** Resolves `true` when the server holds `next` afterwards — either it was
   *  already saved or this save succeeded — and `false` when the save failed. */
  const flush = useCallback(
    (next: Data): Promise<boolean> => {
      pendingRef.current = null;
      const run = queueRef.current.then(() => send(next));
      queueRef.current = run.catch(() => undefined);
      return run;
    },
    [send],
  );

  /** Leaving the screen inside the debounce window must not drop the last edit. */
  useEffect(
    () => () => {
      if (pendingRef.current) void flush(pendingRef.current);
    },
    [flush],
  );

  /** Puck's `onChange`. Debounced — see `AUTOSAVE_DELAY_MS`. */
  const change = useCallback(
    (next: Data) => {
      setData(next);
      pendingRef.current = next;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(next), AUTOSAVE_DELAY_MS);
    },
    [flush],
  );

  /** Save now, without waiting for the timer — the toolbar's Save. */
  const saveNow = useCallback(async (): Promise<boolean> => {
    if (timerRef.current) clearTimeout(timerRef.current);
    return data ? flush(data) : true;
  }, [data, flush]);

  const publish = useCallback(
    () =>
      guard(async () => {
        setError(null);
        // The pending draft goes first. Publishing snapshots whatever the server
        // holds, so skipping this would put the *previous* draft in front of
        // readers and leave the writer looking at something else entirely.
        // A failed save stops here: `flush` reports it rather than throwing, and
        // carrying on would publish the *previous* draft while the writer's
        // screen still shows the unsaved one.
        if (!(await saveNow())) return;
        await publishArticle(articleId);
        await load();
      }).catch((e) => setError((e as Error).message)),
    [articleId, guard, load, saveNow],
  );

  /** Discard the edits on screen for the server's copy — only ever by choice. */
  const reload = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    pendingRef.current = null;
    conflictRef.current = false;
    setConflict(false);
    setError(null);
    setSaveState('idle');
    await load();
    setReloadKey((k) => k + 1);
  }, [load]);

  const dirty = data !== null && JSON.stringify(data) !== savedRef.current;

  return {
    article,
    data,
    saveState,
    error,
    busy,
    dirty,
    conflict,
    reloadKey,
    load,
    change,
    saveNow,
    publish,
    reload,
  };
}
