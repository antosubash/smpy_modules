import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import { deleteRecord, purgeRecord, restoreRecord } from '../utils/api';
import type { RecordRead } from '../utils/types';
import { ConfirmDialog } from './ConfirmDialog';
import { RecordDeleteDialog } from './RecordDeleteDialog';

/** Delete / restore / purge for `RecordEditor` — split out so the editor's
 *  main body stays readable and under the 300-line cap. Exactly one of the
 *  two branches renders, depending on `record.is_deleted`. */
export function RecordActions({
  typeKey,
  record,
  onRestored,
  onGone,
}: {
  typeKey: string;
  record: RecordRead;
  onRestored: (restored: RecordRead) => void;
  onGone: () => void;
}) {
  const { t } = useT();
  const cancelLabel = t('records.editor.cancel', { defaultValue: 'Cancel' });
  const pendingLabel = t('records.editor.saving', { defaultValue: 'Saving…' });

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
          onGone();
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
        cancelLabel={cancelLabel}
        pendingLabel={pendingLabel}
        onConfirm={async () => onRestored(await restoreRecord(typeKey, record.uuid))}
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
        cancelLabel={cancelLabel}
        pendingLabel={pendingLabel}
        destructive
        onConfirm={async () => {
          await purgeRecord(typeKey, record.uuid);
          onGone();
        }}
      />
    </>
  );
}
