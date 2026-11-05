/**
 * Load a campaign, autosave its body and details, refresh its cards.
 *
 * Every write carries the `revision` it was made against (`expected_revision`,
 * ruling C3) and adopts the one the server answers with. A 409 `stale` or
 * `not_a_draft` means someone else changed the campaign (or it left draft):
 * the editor stops saving and asks the writer to reload, rather than retrying
 * a write that would only be refused again.
 *
 * One request at a time: the timer, `refresh` and unmount all go through one
 * queue, so a later write never carries a revision from before an earlier one
 * landed and gets refused as a conflict with itself.
 */

import type { Data } from '@puckeditor/core';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../utils/api';
import { isComplete, normalizeBody } from '../utils/bodyDraft';
import { errorMessage, isCode } from '../utils/http';
import { useT } from '../utils/i18n';
import { fromPuckData, toPuckData } from '../utils/puckData';
import type { Block, CampaignDetail } from '../utils/types';

/** How long after the last edit a save fires: a sentence is one request, and
 *  closing the tab loses a moment's work at most. */
export const AUTOSAVE_DELAY_MS = 1500;

export type EditorStatus = 'idle' | 'saving' | 'saved' | 'stale' | 'error';

/** The campaign's own fields the editor writes besides the body. */
export type MetaPatch = Partial<
  Pick<CampaignDetail, 'name' | 'subject' | 'preheader' | 'from_name' | 'reply_to'>
>;

const EMPTY: Data = { root: { props: {} }, content: [] };

function isStale(e: unknown): boolean {
  return isCode(e, 'stale') || isCode(e, 'not_a_draft');
}

export function useCampaignEditor(id: number) {
  const { t } = useT();
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [data, setData] = useState<Data>(EMPTY);
  const [status, setStatus] = useState<EditorStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [incomplete, setIncomplete] = useState(false);
  /** Bumped when the body is replaced from outside Puck, so the canvas remounts. */
  const [reloadKey, setReloadKey] = useState(0);

  const revisionRef = useRef(0);
  /** The normalised body the server holds, serialised: a save fires only for a real change
   *  (Puck's `onChange` also runs on selection). */
  const savedBodyRef = useRef('[]');
  const dataRef = useRef<Data>(EMPTY);
  /** What the next save carries: a complete body that differs from the saved one, and meta. */
  const bodyRef = useRef<Block[] | null>(null);
  const metaRef = useRef<MetaPatch>({});
  const staleRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());

  const clearTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  /** Adopt the server's campaign; edits typed while the request was out stay on top. */
  const adopt = useCallback((detail: CampaignDetail) => {
    revisionRef.current = detail.revision;
    savedBodyRef.current = JSON.stringify(normalizeBody(detail.body));
    setCampaign({ ...detail, ...metaRef.current });
  }, []);

  const fail = useCallback(
    (e: unknown) => {
      if (isStale(e)) {
        staleRef.current = true;
        clearTimer();
        setStatus('stale');
      } else {
        setStatus('error');
      }
      setError(errorMessage(e, t));
    },
    [clearTimer, t],
  );

  const load = useCallback(async () => {
    try {
      const detail = await api.getCampaign(id);
      adopt(detail);
      const next = toPuckData(detail.body);
      dataRef.current = next;
      setData(next);
    } catch (e) {
      fail(e);
    }
  }, [adopt, fail, id]);

  useEffect(() => {
    void load();
  }, [load]);

  /** One PATCH with whatever is pending. Resolves `false` when something stayed unsaved. */
  const send = useCallback(async (): Promise<boolean> => {
    if (staleRef.current) return false;
    const meta = metaRef.current;
    const body = bodyRef.current;
    const serialized = body ? JSON.stringify(body) : null;
    const withBody = serialized !== null && serialized !== savedBodyRef.current;
    if (!withBody && Object.keys(meta).length === 0) return true;
    metaRef.current = {};
    bodyRef.current = null;
    setStatus('saving');
    try {
      const detail = await api.patchCampaign(id, {
        expected_revision: revisionRef.current,
        ...meta,
        ...(withBody ? { body: body as Block[] } : {}),
      });
      adopt(detail);
      setStatus('saved');
      setError(null);
      return true;
    } catch (e) {
      // Kept for the next try, under anything typed since.
      metaRef.current = { ...meta, ...metaRef.current };
      if (withBody && bodyRef.current === null) bodyRef.current = body;
      fail(e);
      return false;
    }
  }, [adopt, fail, id]);

  const enqueue = useCallback(<T>(task: () => Promise<T>): Promise<T> => {
    const run = queueRef.current.then(task);
    queueRef.current = run.catch(() => undefined);
    return run;
  }, []);

  const flush = useCallback(() => {
    clearTimer();
    return enqueue(send);
  }, [clearTimer, enqueue, send]);

  const schedule = useCallback(() => {
    if (staleRef.current) return;
    clearTimer();
    timerRef.current = setTimeout(() => void flush(), AUTOSAVE_DELAY_MS);
  }, [clearTimer, flush]);

  /** Puck's `onChange`. */
  const onChange = useCallback(
    (next: Data) => {
      dataRef.current = next;
      setData(next);
      const body = normalizeBody(fromPuckData(next));
      const complete = body.every(isComplete);
      setIncomplete(!complete);
      bodyRef.current = complete && JSON.stringify(body) !== savedBodyRef.current ? body : null;
      if (bodyRef.current) schedule();
    },
    [schedule],
  );

  /** A change to the campaign's details, saved with the same debounce as the body. */
  const saveMeta = useCallback(
    (patch: MetaPatch) => {
      metaRef.current = { ...metaRef.current, ...patch };
      setCampaign((c) => (c ? { ...c, ...patch } : c));
      schedule();
    },
    [schedule],
  );

  /** Re-snapshot one card server-side. The pending autosave goes first, so the
   *  refresh is made against the revision that holds it; if it could not be
   *  saved, nothing is refreshed (adopting the server's body would drop it). */
  const refresh = useCallback(
    async (blockId: string): Promise<void> => {
      if (!(await flush())) return;
      await enqueue(async () => {
        if (staleRef.current) return;
        setStatus('saving');
        try {
          const detail = await api.refreshCard(id, blockId, revisionRef.current);
          adopt(detail);
          // Only this block changes on screen; anything else not yet saved
          // (an unfinished block) stays as it is.
          const fresh = detail.body.find((b) => b.props.id === blockId);
          const next: Data = {
            ...dataRef.current,
            content: dataRef.current.content.map((item) =>
              fresh && item.props.id === blockId
                ? { type: fresh.type, props: { ...fresh.props } }
                : item,
            ),
          };
          dataRef.current = next;
          setData(next);
          setReloadKey((k) => k + 1);
          setStatus('saved');
          setError(null);
        } catch (e) {
          fail(e);
        }
      });
    },
    [adopt, enqueue, fail, flush, id],
  );

  /** Drop what is on screen for the server's copy: the way out of `stale`. */
  const reload = useCallback(async () => {
    clearTimer();
    staleRef.current = false;
    bodyRef.current = null;
    metaRef.current = {};
    setIncomplete(false);
    setError(null);
    setStatus('idle');
    await load();
    setReloadKey((k) => k + 1);
  }, [clearTimer, load]);

  /** Leaving inside the debounce window must not drop the last edit. */
  useEffect(
    () => () => {
      if (timerRef.current) void flush();
    },
    [flush],
  );

  return {
    campaign,
    data,
    onChange,
    saveMeta,
    status,
    error,
    incomplete,
    refresh,
    reload,
    reloadKey,
  };
}
