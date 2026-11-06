/**
 * What the campaign editor has on screen that the server does not hold yet.
 *
 * Split out of `useCampaignEditor`, which owns the requests: this owns the
 * bookkeeping they read and write — the next save's body and meta, the
 * debounce timer, the requests in flight, an unfinished block or audience
 * choice — and turns it into the one `dirty` flag the page guards leaving with.
 *
 * `edits` is one object for the editor's lifetime (mutable fields, like refs),
 * so callbacks can depend on it without being rebuilt.
 */

import { useState } from 'react';

import type { Block, CampaignDetail } from '../utils/types';

/** The campaign's own fields the editor writes besides the body. */
export type MetaPatch = Partial<
  Pick<CampaignDetail, 'name' | 'subject' | 'preheader' | 'from_name' | 'reply_to' | 'audience'>
>;

export interface PendingEdits {
  /** The next save's body: complete, and different from the saved one. */
  body: Block[] | null;
  /** The next save's campaign fields. */
  meta: MetaPatch;
  /** The body is held back because a block lacks a required field. */
  incomplete: boolean;
  /** A tag or segment audience is chosen but no value yet: the saved audience
   *  is still the old one, so nothing may be sent. */
  audienceUnfinished: boolean;
  inFlight: number;
  timer: ReturnType<typeof setTimeout> | null;
  hasPending(): boolean;
  /** Recompute `dirty`: a save is waiting (timer), running, or left over after
   *  a failure, or the body is held back. Leaving then loses work. */
  sync(): void;
  clearTimer(): void;
  markIncomplete(value: boolean): void;
  markAudienceUnfinished(value: boolean): void;
  /** What a real send must not go out with: an unfinished block or audience. */
  blocked(): boolean;
  /** A save takes what is pending and goes out: nothing is pending, one more in flight. */
  begin(): void;
  /** The save came back, either way. */
  end(): void;
  /** A failed save's edits go back, under anything typed since. */
  restore(meta: MetaPatch, body: Block[] | null): void;
  /** Forget everything pending (a reload from the server). */
  reset(): void;
}

export function usePendingEdits() {
  const [dirty, setDirty] = useState(false);
  const [incomplete, setIncomplete] = useState(false);
  const [audienceUnfinished, setAudienceUnfinished] = useState(false);
  const [edits] = useState<PendingEdits>(() => {
    const e: PendingEdits = {
      body: null,
      meta: {},
      incomplete: false,
      audienceUnfinished: false,
      inFlight: 0,
      timer: null,
      hasPending: () => e.body !== null || Object.keys(e.meta).length > 0,
      sync: () => setDirty(e.timer !== null || e.inFlight > 0 || e.hasPending() || e.blocked()),
      clearTimer: () => {
        if (e.timer) clearTimeout(e.timer);
        e.timer = null;
      },
      markIncomplete: (value) => {
        e.incomplete = value;
        setIncomplete(value);
      },
      markAudienceUnfinished: (value) => {
        e.audienceUnfinished = value;
        setAudienceUnfinished(value);
        e.sync();
      },
      blocked: () => e.incomplete || e.audienceUnfinished,
      begin: () => {
        e.meta = {};
        e.body = null;
        e.inFlight += 1;
        e.sync();
      },
      end: () => {
        e.inFlight -= 1;
        e.sync();
      },
      restore: (meta, body) => {
        e.meta = { ...meta, ...e.meta };
        if (body && e.body === null) e.body = body;
      },
      reset: () => {
        e.clearTimer();
        e.body = null;
        e.meta = {};
        e.markIncomplete(false);
        e.markAudienceUnfinished(false);
      },
    };
    return e;
  });
  return { dirty, incomplete, audienceUnfinished, edits };
}
