import { router } from '@inertiajs/react';
import { purgedToast, restoredToast, trashToast } from '../components/trashToast';
import { deleteRecord, purgeRecord, restoreRecord } from '../utils/api-records';
import type { Translate } from '../utils/translate';
import type { RecordRead } from '../utils/types';

/**
 * The three row mutations `RecordList` hands down to `RecordTable` — split
 * out of the page component so it stays under the 300-line cap. Each one
 * reloads just the `records` prop and raises the toast the action owes the
 * operator (UX-R8, U4/U9): a soft delete gets one with Undo, a restore and a
 * permanent delete get a plain confirmation, since neither has an undo to
 * offer.
 */
export function useRecordListMutations(typeKey: string, t: Translate) {
  const handleRestore = async (record: RecordRead) => {
    await restoreRecord(typeKey, record.uuid);
    router.reload({ only: ['records'] });
    restoredToast(t);
  };

  const handleDelete = async (record: RecordRead) => {
    await deleteRecord(typeKey, record.uuid);
    router.reload({ only: ['records'] });
    // A soft delete that said nothing at all was a reversible action wearing
    // an irreversible one's face (UX-R8): the toast names the Trash, undoes
    // the delete, and links the trashed view for anyone who reads it late.
    trashToast(t, { typeKey, onUndo: () => handleRestore(record) });
  };

  // U4: the Trash view's only recovery from a stuck unique value or slug
  // used to be Restore-edit-retrash. Purge is irreversible (no Undo action
  // on the toast, unlike handleDelete's trashToast above) and only ever
  // reachable from an already-trashed row (RecordRowAction gates it on
  // `trashed`), so there is no confirmation to add here beyond the
  // ConfirmDialog the row action already shows before this runs.
  const handlePurge = async (record: RecordRead) => {
    await purgeRecord(typeKey, record.uuid);
    router.reload({ only: ['records'] });
    purgedToast(t);
  };

  return { handleDelete, handleRestore, handlePurge };
}
