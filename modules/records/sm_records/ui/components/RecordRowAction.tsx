import { Button } from '@simple-module-py/ui/components/ui/button';
import { keys, useT } from '../utils/i18n';

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
  title,
  trashed,
  onDelete,
  onRestore,
  onPurge,
}: {
  typeKey: string;
  record: RecordRead;
  /** U5: the record's display title, or the caller's own fallback
   *  (`recordDisplayTitle`) when it has none — so the accessible name is
   *  never "Delete " for a record whose display field is empty, exactly the
   *  invalid worklist's case. */
  title: string;
  trashed: boolean;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
  /** U4: a trashed record otherwise has no way out of the Trash except
   *  Restore, which is not what an operator wants when the point is to
   *  release the unique value / slug a trashed row still holds. Only
   *  consulted when `trashed`; live rows never render "Delete permanently"
   *  from the list (that stays an editor-only action, same as before). */
  onPurge: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  // U27: every row's Delete/Restore/Delete-permanently button had the exact
  // same accessible name — 25 identical "Delete"s on a page a screen-reader
  // user navigates by name. The visible label stays short (a table cell has
  // no room for "Delete Deluxe Sleeping Bag" on every row); `aria-label`
  // carries the record's title the same way the relation chips' own
  // "Remove {title}" button already does.
  if (trashed) {
    const restoreLabel = t(keys.records.editor.restore);
    const purgeLabel = t(keys.records.editor.purge);
    return (
      <div className="flex justify-end gap-1">
        <ConfirmDialog
          trigger={
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={t(keys.records.records.restore_named, {
                title,
              })}
            >
              {restoreLabel}
            </Button>
          }
          title={restoreLabel}
          description={t(keys.records.editor.confirm_restore)}
          confirmLabel={restoreLabel}
          onConfirm={() => onRestore(record)}
        />
        <ConfirmDialog
          trigger={
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              aria-label={t(keys.records.records.purge_named, {
                title,
              })}
            >
              {purgeLabel}
            </Button>
          }
          title={purgeLabel}
          description={t(keys.records.editor.confirm_purge)}
          confirmLabel={purgeLabel}
          destructive
          onConfirm={() => onPurge(record)}
        />
      </div>
    );
  }
  return (
    <RecordDeleteDialog
      typeKey={typeKey}
      uuid={record.uuid}
      trigger={
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t(keys.records.records.delete_named, {
            title,
          })}
        >
          {t(keys.records.records.delete)}
        </Button>
      }
      onConfirm={() => onDelete(record)}
    />
  );
}
