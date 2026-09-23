import { Link, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type React from 'react';

import type { FieldDef } from '../utils/types';
import { RecordIoMenu } from './RecordIoMenu';

/**
 * The record list's toolbar: back to the types, the column chooser, export
 * and import, the trash toggle and "New record". Split out of
 * `pages/RecordList.tsx` for the 300-line cap.
 *
 * `PageShell` lays its own `actions` row out `flex-shrink-0` with no
 * wrapping (it lives in the framework's `@simple-module-py/ui` package,
 * which this module cannot change), so four buttons ran straight off a
 * 390px document and took the whole page's horizontal scroll with them
 * (UX-R4). Below `sm` that row is a full-width column item, so a wrapping
 * flex row inside it is the fix from this side of the boundary.
 */
export function RecordListActions({
  typeKey,
  fields,
  canEdit,
  trashed,
  exportSearch,
  filtered,
  recordCount,
  maxImportBytes,
  columnsMenu,
  onToggleTrashed,
}: {
  typeKey: string;
  fields: FieldDef[];
  canEdit: boolean;
  trashed: boolean;
  /** `search` and not `''`: "Export" means "export what this screen is
   *  showing", so the current `filter`/`sort`/`trashed` travel with it —
   *  `exportUrl` drops the paging params (`page`, `after`), the caller drops
   *  the display-only `columns`, and `exportSearchParams` drops a `filter`
   *  the list is already showing an error for (polish note: that download
   *  is a raw JSON 400 in a new tab). */
  exportSearch: string;
  /** U16: export honours the list's current filter, so the menu says so —
   *  the caller mirrors `exportSearch` here rather than claiming "filtered"
   *  for an export that will not actually be one. */
  filtered: boolean;
  recordCount: number;
  maxImportBytes?: number;
  /** The "Columns" menu, when the list has anything to show columns of. */
  columnsMenu?: React.ReactNode;
  onToggleTrashed: () => void;
}) {
  const { t } = useT();
  return (
    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
      <Button variant="outline" onClick={() => router.visit('/admin/records')}>
        {t('records.types.title', { defaultValue: 'Record Types' })}
      </Button>
      {columnsMenu}
      <RecordIoMenu
        typeKey={typeKey}
        search={exportSearch}
        canEdit={canEdit}
        fields={fields}
        trashed={trashed}
        filtered={filtered}
        recordCount={recordCount}
        {...(maxImportBytes ? { maxImportBytes } : {})}
      />
      {canEdit && (
        <Button
          type="button"
          variant={trashed ? 'default' : 'outline'}
          data-testid="records-trash-toggle"
          onClick={onToggleTrashed}
        >
          {trashed
            ? t('records.trash.view_live', { defaultValue: 'Back to live records' })
            : t('records.trash.view', { defaultValue: 'Trash' })}
        </Button>
      )}
      {!trashed && (
        <Button asChild>
          <Link href={`/admin/records/${typeKey}/new`}>
            {t('records.records.new', { defaultValue: 'New record' })}
          </Link>
        </Button>
      )}
    </div>
  );
}
