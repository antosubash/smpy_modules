/**
 * What the campaign editor has on screen that the server does not hold yet.
 *
 * Split out of `useCampaignEditor`, which owns the requests: this owns the
 * bookkeeping they read and write — the next save's body and meta, the
 * debounce timer, the requests in flight, an unfinished block — and turns it
 * into the one `dirty` flag the page guards leaving with.
 *
 * `edits` is one object for the editor's lifetime (mutable fields, like refs),
 * so callbacks can depend on it without being rebuilt.
 */

import { useState } from 'react';

import type { Block, CampaignDetail } from '../utils/types';

/** The campaign's own fields the editor writes besides the body. */
export type MetaPatch = Partial<
  Pick<CampaignDetail, 'name' | 'subject' | 'preheader' | 'from_name' | 'reply_to'>
>;

interface PendingEdits {
  /** The next save's body: complete, and different from the saved one. */
  body: Block[] | null;
  /** The next save's campaign fields. */
  meta: MetaPatch;
  /** The body is held back because a block lacks a required field. */
  incomplete: boolean;
  /** Details fields whose typed value the server would refuse, so it was never sent. */
  invalid: Set<string>;
  inFlight: number;
  timer: ReturnType<typeof setTimeout> | null;
  hasPending(): boolean;
  /** Recompute `dirty`: a save is waiting (timer), running, or left over after
   *  a failure, or the body is held back. Leaving then loses work. */
  sync(): void;
  clearTimer(): void;
  markIncomplete(value: boolean): void;
  markInvalid(field: string, value: boolean): void;
}

export function usePendingEdits() {
  const [dirty, setDirty] = useState(false);
  const [incomplete, setIncomplete] = useState(false);
  const [metaInvalid, setMetaInvalid] = useState(false);
  const [edits] = useState<PendingEdits>(() => {
    const e: PendingEdits = {
      body: null,
      meta: {},
      incomplete: false,
      invalid: new Set<string>(),
      inFlight: 0,
      timer: null,
      hasPending: () => e.body !== null || Object.keys(e.meta).length > 0,
      sync: () =>
        setDirty(
          e.timer !== null ||
            e.inFlight > 0 ||
            e.hasPending() ||
            e.incomplete ||
            e.invalid.size > 0,
        ),
      clearTimer: () => {
        if (e.timer) clearTimeout(e.timer);
        e.timer = null;
      },
      markIncomplete: (value) => {
        e.incomplete = value;
        setIncomplete(value);
      },
      markInvalid: (field, value) => {
        if (value) {
          e.invalid.add(field);
          // An earlier, still-queued value of this field must not be saved under it.
          delete (e.meta as Record<string, unknown>)[field];
        } else e.invalid.delete(field);
        setMetaInvalid(e.invalid.size > 0);
        e.sync();
      },
    };
    return e;
  });
  return { dirty, incomplete, metaInvalid, edits };
}
