import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import { deleteRecord, purgeRecord, restoreRecord } from '../utils/api-records';
import type { RecordRead } from '../utils/types';
import { ConfirmDialog } from './ConfirmDialog';
import { RecordDeleteDialog } from './RecordDeleteDialog';
import { restoredToast, trashToast } from './trashToast';

/** Delete / restore / purge for `RecordEditor` — split out so the editor's
 *  main body stays readable and under the 300-line cap. Exactly one of the
 *  two branches renders, depending on `record.is_deleted`. */
export function RecordActions({
  typeKey,
  record,
  allowNavigation,
  onRestored,
  onGone,
}: {
  typeKey: string;
  record: RecordRead;
  /** `useRecordEditor`'s `allowNavigation`, called immediately before
   *  `onGone()` (R4). `onGone` is an ordinary Inertia visit, so a dirty form
   *  otherwise made `useUnsavedGuard` ask "you have unsaved changes, leave
   *  this page?" about a record that no longer exists — and cancelling left
   *  the person on the editor of a deleted one. The create path already
   *  does exactly this before its own visit. */
  allowNavigation?: () => void;
  onRestored: (restored: RecordRead) => void;
  onGone: () => void;
}) {
  const { t } = useT();
  /** The work is written (or the record is gone); the guard must not ask
   *  about it on the way out. */
  const leave = () => {
    allowNavigation?.();
    onGone();
  };

  if (!record.is_deleted) {
    const label = t('records.records.delete', { defaultValue: 'Delete' });
    return (
      <RecordDeleteDialog
        typeKey={typeKey}
        uuid={record.uuid}
        trigger={
          <Button type="button" variant="outline">
            {label}
          </Button>
        }
        onConfirm={async () => {
          await deleteRecord(typeKey, record.uuid);
          // Before `onGone()` navigates: the toast names the Trash the
          // record went to and offers to put it back (UX-R8). `RecordsToaster`
          // is mounted by the layout both screens share, so the toast
          // survives the visit to the list that follows.
          trashToast(t, {
            typeKey,
            onUndo: async () => {
              await restoreRecord(typeKey, record.uuid);
              restoredToast(t);
              router.reload({ only: ['records'] });
            },
          });
          leave();
        }}
      />
    );
  }

  const restoreLabel = t('records.editor.restore', { defaultValue: 'Restore' });
  const purgeLabel = t('records.editor.purge', { defaultValue: 'Delete permanently' });
  return (
    <>
      <ConfirmDialog
        trigger={
          <Button type="button" variant="outline">
            {restoreLabel}
          </Button>
        }
        title={restoreLabel}
        description={t('records.editor.confirm_restore', {
          defaultValue: 'Restore this record?',
        })}
        confirmLabel={restoreLabel}
        onConfirm={async () => {
          onRestored(await restoreRecord(typeKey, record.uuid));
          restoredToast(t);
        }}
      />
      <ConfirmDialog
        trigger={
          <Button type="button" variant="destructive">
            {purgeLabel}
          </Button>
        }
        title={purgeLabel}
        description={t('records.editor.confirm_purge', {
          defaultValue: 'This cannot be undone. Delete this record permanently?',
        })}
        confirmLabel={purgeLabel}
        destructive
        onConfirm={async () => {
          await purgeRecord(typeKey, record.uuid);
          leave();
        }}
      />
    </>
  );
}
