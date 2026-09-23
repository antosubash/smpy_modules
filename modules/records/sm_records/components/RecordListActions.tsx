import { Link, router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type React from 'react';

import type { FieldDef, TenancyMode } from '../utils/types';
import { RecordIoMenu } from './RecordIoMenu';
import { TenantBadge } from './TenantBadge';

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
 *
 * From `sm` up the row sits *beside* the title, and `flex-shrink-0` sizes
 * the wrapper to its content's max-content width, so `flex-wrap` alone
 * never wraps: six buttons pushed a 720px document to 745px (review 4, ux
 * F1 — WCAG 1.4.10 reflow at 200% zoom). `TOOLBAR_CLASS` caps the group's
 * own width against the viewport instead, which is the one width a
 * content-sized parent cannot hide: the page's padding (3rem; plus the 16rem
 * sidebar from `lg`) and about 12rem for the title are left over, and the
 * buttons wrap into what remains. At 1280px and wider nothing wraps.
 */
/** Exported for the test that pins it: layout is not measurable in the
 *  unit tests' DOM, so the classes are the contract (the e2e checks the
 *  document width at 720 and 390px). */
export const TOOLBAR_CLASS =
  'flex min-w-0 flex-wrap items-center gap-2 sm:max-w-[calc(100vw-15rem)] sm:justify-end lg:max-w-[calc(100vw-32rem)]';

export function RecordListActions({
  typeKey,
  fields,
  canEdit,
  trashed,
  exportSearch,
  filtered,
  recordCount,
  recordCountCapped = false,
  maxImportBytes,
  columnsMenu,
  tenant,
  tenancyMode,
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
  /** `records.total_capped` — the export menu then says "N+". */
  recordCountCapped?: boolean;
  maxImportBytes?: number;
  /** The "Columns" menu, when the list has anything to show columns of. */
  columnsMenu?: React.ReactNode;
  /** Tenancy design §J — read-only; renders `TenantBadge` in this toolbar. */
  tenant?: string;
  tenancyMode?: TenancyMode;
  onToggleTrashed: () => void;
}) {
  const { t } = useT();
  return (
    <div className={TOOLBAR_CLASS} data-testid="records-list-actions">
      <TenantBadge tenant={tenant} tenancyMode={tenancyMode} />
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
        recordCountCapped={recordCountCapped}
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
