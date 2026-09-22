import { router } from '@inertiajs/react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '../utils/api';
import { type BulkAction, type BulkReport, bulkRecords, emptyTrash } from '../utils/api-records';

// See `pages/RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** What each action says when it worked. One key per action rather than a
 *  built string: a sentence assembled from a verb and a count is a sentence
 *  no translator can reorder. */
const DONE: Record<BulkAction, [string, string]> = {
  trash: ['records.bulk.done_trash', '{count} records moved to the Trash'],
  restore: ['records.bulk.done_restore', '{count} records restored'],
  purge: ['records.bulk.done_purge', '{count} records deleted permanently'],
  publish: ['records.bulk.done_publish', '{count} records published'],
  unpublish: ['records.bulk.done_unpublish', '{count} records returned to draft'],
};

/**
 * Running a bulk action, and what the screen says afterwards.
 *
 * Three outcomes and each needs a different answer. It worked: reload the
 * list, toast, drop the selection — the rows the operator ticked are not
 * the rows on screen any more. The toast (U11) is the *only* announcement a
 * success gets, the same as every single-row action in this module
 * (`trashToast`/`restoredToast`/`purgedToast`) already relies on sonner's
 * own live region for. **It was refused**: the server changed nothing and
 * named the records that refused, so the report goes on screen
 * (`BulkRefusalReport`) and the *selection stays*, because the next step is
 * to deselect those and retry — this is the one outcome that still writes
 * to `announcement`, since it has no toast of its own. Anything else —
 * offline, a 403, a 500 — is re-thrown for `ConfirmDialog`, which shows it
 * inside the dialog the operator is still looking at.
 *
 * Resolving on a refusal rather than re-throwing is what closes that dialog:
 * a report of up to `max_bulk_records` lines is not something to read through
 * a modal, and the panel it lands in sits next to the checkboxes it is about.
 */
export function useBulkActions(
  typeKey: string,
  t: Translate,
  {
    uuids,
    filters = [],
    onDone,
    resetKey,
  }: {
    /** The selection, in page order — what the request names. */
    uuids: string[];
    /** Every `filter=` term the list is showing, for "empty this filtered
     *  trash": the server ANDs them, and sending fewer would empty more. */
    filters?: readonly string[];
    onDone: () => void;
    /** U2: the identity of "this page", the same way `useRecordSelection`'s
     *  own `key` is — a page/filter/sort change (or the reload a bulk
     *  action itself triggers) changes it. The refusal report goes with it:
     *  a stale report names uuids that may no longer be on screen, and the
     *  selection it was about has already been reset by the same change. */
    resetKey: string;
  },
) {
  const [report, setReport] = useState<BulkReport | null>(null);
  const [pending, setPending] = useState(false);
  const [announcement, setAnnouncement] = useState('');

  const previousResetKey = useRef(resetKey);
  useEffect(() => {
    if (previousResetKey.current === resetKey) return;
    previousResetKey.current = resetKey;
    setReport(null);
    // The refusal sentence is the only thing that still writes here (see
    // `announceDone` below) — goes with the report it was about, same
    // trigger.
    setAnnouncement('');
  }, [resetKey]);

  // U11: a *successful* action already has an accessible announcement —
  // sonner's own toast region — the same one every single-row action in
  // this module relies on alone (`trashToast`/`restoredToast`/`purgedToast`,
  // none of which write to a live region of their own). Writing the same
  // text into `announcement` too doubled it for a screen-reader user (the
  // module's own `role="status"` region and sonner's, back to back). The
  // *refusal* case below is different and keeps using `announcement`
  // directly: it has no toast, so the live region is the only announcement
  // it gets.
  const announceDone = (message: string) => {
    toast.success(message);
  };

  const run = async (action: BulkAction) => {
    setPending(true);
    setReport(null);
    try {
      const result = await bulkRecords(typeKey, action, uuids);
      const [key, defaultValue] = DONE[action];
      // A batch of records that were all already published changed nothing,
      // and "0 records published" is not what to say about it. Its own
      // sentence rather than the action's with a zero in it.
      let message =
        result.changed === 0 && result.unchanged > 0
          ? t('records.bulk.done_unchanged_only', {
              count: result.unchanged,
              defaultValue: '{count} records were already in that state; nothing changed.',
            })
          : t(key, { count: result.changed, defaultValue });
      if (result.changed > 0 && result.unchanged > 0) {
        message = `${message} ${t('records.bulk.done_unchanged', {
          count: result.unchanged,
          defaultValue: '{count} were already in that state.',
        })}`;
      }
      if (result.cascaded > 0) {
        message = `${message} ${t('records.bulk.done_cascaded', {
          count: result.cascaded,
          defaultValue: '{count} related records went with them.',
        })}`;
      }
      router.reload({ only: ['records'] });
      onDone();
      announceDone(message);
    } catch (err) {
      const body = err instanceof ApiError && err.status === 409 ? err.body?.report : undefined;
      // `report` carries a schema dry run on one route and this on another;
      // `failed` is what tells them apart, and it is the only one of the two
      // a record list can ever receive.
      if (body && 'failed' in body) {
        const refusal = body as BulkReport;
        setReport(refusal);
        // Announced as well as rendered: a screen-reader user who confirmed
        // the dialog is told the batch did nothing, not left with a panel
        // that appeared silently behind the dialog they just dismissed.
        setAnnouncement(
          t('records.bulk.refused', {
            count: refusal.failed.length,
            total: refusal.requested,
            defaultValue:
              '{count} of {total} records could not be changed, so nothing was changed.',
          }),
        );
        return;
      }
      throw err;
    } finally {
      setPending(false);
    }
  };

  const empty = async (filtered: boolean) => {
    setPending(true);
    try {
      const result = await emptyTrash(typeKey, filtered ? filters : []);
      router.reload({ only: ['records'] });
      onDone();
      announceDone(
        t('records.bulk.done_empty_trash', {
          count: result.purged,
          defaultValue: '{count} records deleted permanently',
        }),
      );
    } finally {
      setPending(false);
    }
  };

  return {
    report,
    pending,
    announcement,
    run,
    empty,
    dismissReport: () => setReport(null),
  };
}
