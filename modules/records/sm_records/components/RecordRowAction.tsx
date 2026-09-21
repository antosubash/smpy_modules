import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { RecordRead } from '../utils/types';
import { ConfirmDialog } from './ConfirmDialog';
import { RecordDeleteDialog } from './RecordDeleteDialog';

/**
 * The one action a record list row carries: "Delete" on a live row, or
 * "Restore" on a trashed one (deleting an already-trashed row means nothing,
 * and restoring a live one means less).
 *
 * Shared by the two renderings of the same list — the `<Table>` above `sm`
 * and the stacked cards below it (UX-R4) — so the phone layout cannot drift
 * away from the desktop one's behaviour, which is exactly how the action
 * column ended up off the edge of the document in the first place.
 */
export function RecordRowAction({
  typeKey,
  record,
  trashed,
  onDelete,
  onRestore,
}: {
  typeKey: string;
  record: RecordRead;
  trashed: boolean;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  if (trashed) {
    const restoreLabel = t('records.editor.restore', { defaultValue: 'Restore' });
    return (
      <ConfirmDialog
        trigger={
          <Button type="button" variant="ghost" size="sm">
            {restoreLabel}
          </Button>
        }
        title={restoreLabel}
        description={t('records.editor.confirm_restore', { defaultValue: 'Restore this record?' })}
        confirmLabel={restoreLabel}
        cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
        pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
        onConfirm={() => onRestore(record)}
      />
    );
  }
  return (
    <RecordDeleteDialog
      typeKey={typeKey}
      uuid={record.uuid}
      trigger={
        <Button type="button" variant="ghost" size="sm">
          {t('records.records.delete', { defaultValue: 'Delete' })}
        </Button>
      }
      onConfirm={() => onDelete(record)}
    />
  );
}
