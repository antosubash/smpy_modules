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
import { bodyKey, isComplete, normalizeBody } from '../utils/bodyDraft';
import { errorMessage, isCode } from '../utils/http';
import { useT } from '../utils/i18n';
import { fromPuckData, toPuckData } from '../utils/puckData';
import type { Block, CampaignDetail } from '../utils/types';
import { type MetaPatch, usePendingEdits } from './usePendingEdits';

/** How long after the last edit a save fires: a sentence is one request, and
 *  closing the tab loses a moment's work at most. */
export const AUTOSAVE_DELAY_MS = 1500;

export type EditorStatus = 'idle' | 'saving' | 'saved' | 'stale' | 'error';

export type { MetaPatch } from './usePendingEdits';

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
  /** Bumped when the body is replaced from outside Puck, so the canvas remounts. */
  const [reloadKey, setReloadKey] = useState(0);

  const revisionRef = useRef(0);
  /** The normalised body the server holds (`bodyKey`): a save fires only for a real change
   *  (Puck's `onChange` also runs on selection). */
  const savedBodyRef = useRef('[]');
  const dataRef = useRef<Data>(EMPTY);
  const staleRef = useRef(false);
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());
  const { dirty, incomplete, audienceUnfinished, metaInvalid, edits } = usePendingEdits();

  /** Adopt the server's campaign; edits typed while the request was out stay on top. */
  const adopt = useCallback(
    (detail: CampaignDetail) => {
      revisionRef.current = detail.revision;
      savedBodyRef.current = bodyKey(normalizeBody(detail.body));
      setCampaign({ ...detail, ...edits.meta });
    },
    [edits],
  );

  const fail = useCallback(
    (e: unknown) => {
      if (isStale(e)) {
        staleRef.current = true;
        edits.clearTimer();
        setStatus('stale');
      } else {
        setStatus('error');
      }
      setError(errorMessage(e, t));
    },
    [edits, t],
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

  /** The body on screen when it is complete and not what the server holds, else null. */
  const pendingBody = useCallback((): Block[] | null => {
    const body = normalizeBody(fromPuckData(dataRef.current));
    return body.every(isComplete) && bodyKey(body) !== savedBodyRef.current ? body : null;
  }, []);

  /** One PATCH with whatever is pending. Resolves `false` when something stayed unsaved. */
  const send = useCallback(
    async function send(): Promise<boolean> {
      if (staleRef.current) return false;
      const meta = edits.meta;
      const body = edits.body;
      const serialized = body ? bodyKey(body) : null;
      const withBody = serialized !== null && serialized !== savedBodyRef.current;
      if (!withBody && Object.keys(meta).length === 0) {
        // A queued body that now equals what the server holds (an `onChange` that landed
        // while the save carrying it was out) is nothing to save; left set it would
        // keep `dirty` true for good.
        edits.body = null;
        edits.sync();
        return true;
      }
      edits.begin();
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
        // The canvas may have moved while a body was out (an undo back to the
        // body the server held before this save): what it shows is measured
        // against what the server holds now, and any difference goes out next.
        const rest = withBody ? pendingBody() : null;
        // Not when it is what this very request carried: a server that rewrote the
        // body would otherwise be answered with the same save for ever.
        if (rest && bodyKey(rest) !== serialized) {
          edits.body = rest;
          edits.clearTimer();
          return await send();
        }
        return true;
      } catch (e) {
        edits.restore(meta, withBody ? body : null); // kept for the next try
        fail(e);
        return false;
      } finally {
        edits.end();
      }
    },
    [adopt, fail, id, edits, pendingBody],
  );

  const enqueue = useCallback(<T>(task: () => Promise<T>): Promise<T> => {
    const run = queueRef.current.then(task);
    queueRef.current = run.catch(() => undefined);
    return run;
  }, []);

  const save = useCallback(() => {
    edits.clearTimer();
    edits.sync();
    return enqueue(send);
  }, [edits, enqueue, send]);

  /** `save`, but false while a block or the audience is unfinished: a send must wait (A8). */
  const flush = useCallback(async () => (await save()) && !edits.blocked(), [edits, save]);
  const currentRevision = useCallback(() => revisionRef.current, []);

  const schedule = useCallback(() => {
    if (staleRef.current) return;
    edits.clearTimer();
    edits.timer = setTimeout(() => {
      edits.timer = null;
      void save();
    }, AUTOSAVE_DELAY_MS);
    edits.sync();
  }, [edits, save]);

  /** Take `next` as what is on screen and work out what the next save carries. */
  const track = useCallback(
    (next: Data) => {
      dataRef.current = next;
      setData(next);
      const body = normalizeBody(fromPuckData(next));
      const complete = body.every(isComplete);
      edits.markIncomplete(!complete);
      edits.body = complete && bodyKey(body) !== savedBodyRef.current ? body : null;
      if (edits.body) schedule();
      else edits.sync();
    },
    [edits, schedule],
  );

  /** A change to the campaign's details, saved with the same debounce as the body. */
  const saveMeta = useCallback(
    (patch: MetaPatch) => {
      edits.meta = { ...edits.meta, ...patch };
      setCampaign((c) => (c ? { ...c, ...patch } : c));
      schedule();
    },
    [edits, schedule],
  );

  /** The details form reports a field whose typed value cannot be saved (or is fixed again). */
  const markMetaInvalid = useCallback(
    (field: string, invalid: boolean) => edits.markInvalid(field, invalid),
    [edits],
  );

  /** Re-snapshot one card server-side. The pending autosave goes first, so the
   *  refresh is made against the revision that holds it; if it could not be
   *  saved, nothing is refreshed (adopting the server's body would drop it). */
  const refresh = useCallback(
    async (blockId: string): Promise<void> => {
      if (!(await save())) return;
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
          // Recomputed here rather than left to the remount's `onChange`: an
          // edit made while the request was out must not write the old
          // snapshot back over the refresh.
          track(next);
          setReloadKey((k) => k + 1);
          setStatus('saved');
          setError(null);
        } catch (e) {
          fail(e);
        }
      });
    },
    [adopt, enqueue, fail, id, save, track],
  );

  /** Drop what is on screen for the server's copy: the way out of `stale`. */
  const reload = useCallback(async () => {
    edits.reset();
    staleRef.current = false;
    setError(null);
    setStatus('idle');
    await load();
    setReloadKey((k) => k + 1);
  }, [edits, load]);

  /** Leaving must not drop an edit still waiting for its save — inside the
   *  debounce window, or left over after a failed one. */
  useEffect(
    () => () => {
      if (edits.timer || edits.hasPending()) void save();
    },
    [edits, save],
  );

  return {
    campaign,
    data,
    onChange: track, // Puck's `onChange`
    saveMeta,
    /** The audience picker's `onUnfinished`; `audienceUnfinished` blocks a send. */
    holdAudience: edits.markAudienceUnfinished,
    audienceUnfinished,
    markMetaInvalid,
    metaInvalid,
    status,
    error,
    incomplete,
    refresh,
    reload,
    reloadKey,
    dirty,
    /** Save what is pending now; false when something stayed unsaved (the test send). */
    save,
    flush,
    /** The revision the last save produced: read after `flush` for a send's `expected_revision`. */
    currentRevision,
  };
}
